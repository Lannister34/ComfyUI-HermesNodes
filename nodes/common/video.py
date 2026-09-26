"""MP4 encoding and output-path helpers shared by the video nodes."""

import json
import logging
import math
import os
import uuid
from fractions import Fraction

import torch
import folder_paths
from comfy.cli_args import args

logger = logging.getLogger(__name__)

CODECS = ["auto", "h264_nvenc", "libx264"]


def to_uint8_frames(frames):
    """IMAGE batch [F,H,W,C] float 0..1 -> uint8 numpy array.

    Scales and casts on the device the tensor already lives on, then moves uint8 across:
    a quarter of the bytes over PCIe and no CPU-side float math.
    """
    return (frames.clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()


def workflow_metadata(prompt, extra_pnginfo):
    """Workflow + prompt to embed as mp4 tags, so the file can be dragged back into ComfyUI."""
    if args.disable_metadata:
        return None
    metadata = dict(extra_pnginfo or {})
    if prompt is not None:
        metadata["prompt"] = prompt
    return metadata or None


def output_target(filename_prefix, save_output, width, height, temp_prefix):
    """Pick where an mp4 goes: numbered file in output/ or a unique preview file in temp/.

    Returns (absolute_path, ui_entry) where ui_entry is the dict the front end uses with /view.
    """
    if save_output:
        folder, base_name, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, folder_paths.get_output_directory(), width, height
        )
        while os.path.exists(os.path.join(folder, f"{base_name}_{counter:05d}.mp4")):
            counter += 1
        filename = f"{base_name}_{counter:05d}.mp4"
        file_type = "output"
    else:
        folder = folder_paths.get_temp_directory()
        os.makedirs(folder, exist_ok=True)
        filename = f"{temp_prefix}_{uuid.uuid4().hex[:12]}.mp4"
        subfolder = ""
        file_type = "temp"

    ui_entry = {"filename": filename, "subfolder": subfolder, "type": file_type, "format": "video/mp4"}
    return os.path.join(folder, filename), ui_entry


def _pick_codec(codec):
    """'auto' prefers NVENC: on real footage it matches x264 'fast' for speed while leaving
    the CPU free for sampling. Falls back to libx264 when the build lacks it."""
    if codec != "auto":
        return codec
    import av
    try:
        av.codec.Codec("h264_nvenc", "w")
        return "h264_nvenc"
    except Exception:
        return "libx264"


def encode_mp4(frames, fps, out_path, crf=18, codec="auto", audio=None, metadata=None):
    """Encode uint8 [F,H,W,3] RGB frames (plus optional AUDIO) to an h264 mp4."""
    chosen = _pick_codec(codec)
    try:
        _encode_with(frames, fps, out_path, crf, chosen, audio, metadata)
    except Exception as e:
        _remove_quietly(out_path)
        if chosen == "libx264":
            raise
        # a present-but-unusable NVENC (driver refusal, session limit) should not lose the clip
        logger.warning("[Hermes] %s failed (%s); falling back to libx264", chosen, e)
        try:
            _encode_with(frames, fps, out_path, crf, "libx264", audio, metadata)
        except Exception:
            _remove_quietly(out_path)
            raise


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _encode_with(frames, fps, out_path, crf, codec, audio, metadata):
    import av

    num_frames, h, w, _ = frames.shape
    # yuv420p needs even dimensions
    if h % 2 or w % 2:
        h, w = h - h % 2, w - w % 2
        frames = frames[:, :h, :w, :]

    # use_metadata_tags keeps custom mp4 tags (workflow/prompt) that ffmpeg would otherwise drop;
    # faststart moves the moov atom to the front so the tags are readable without a full download
    container = av.open(out_path, mode="w", options={"movflags": "use_metadata_tags+faststart"})
    try:
        for key, value in (metadata or {}).items():
            container.metadata[key] = value if isinstance(value, str) else json.dumps(value)

        stream = container.add_stream(codec, rate=Fraction(fps).limit_denominator(1000))
        stream.width = w
        stream.height = h
        stream.pix_fmt = "yuv420p"
        if codec.endswith("_nvenc"):
            # NVENC spells quality "cq" and its presets are p1..p7; p4 sits where x264 'fast' does
            stream.options = {"cq": str(int(crf)), "preset": "p4", "rc": "vbr"}
        else:
            stream.options = {"crf": str(int(crf)), "preset": "fast"}
            stream.thread_type = "AUTO"
            stream.thread_count = 0

        audio_stream, audio_frame = _prepare_audio(container, audio, fps, num_frames)

        for frame in frames:
            for packet in stream.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

        if audio_stream is not None:
            for packet in audio_stream.encode(audio_frame):
                container.mux(packet)
            for packet in audio_stream.encode(None):
                container.mux(packet)
    finally:
        container.close()


def _prepare_audio(container, audio, fps, num_frames):
    """Add an AAC stream for a ComfyUI AUDIO dict, clipped to the video duration."""
    import av

    if not audio:
        return None, None
    waveform = audio.get("waveform")
    sample_rate = int(audio.get("sample_rate", 0))
    if waveform is None or sample_rate <= 0 or waveform.numel() == 0:
        return None, None

    # waveform: (batch, channels, samples) -> first batch item, clipped to the clip length
    wf = waveform[0, :, :math.ceil(sample_rate / float(fps) * num_frames)]
    layout = {1: "mono", 2: "stereo", 6: "5.1"}.get(wf.shape[0])
    if layout is None:
        # unusual channel count: downmix to stereo rather than mislabel the layout
        wf = wf.mean(dim=0, keepdim=True).expand(2, -1)
        layout = "stereo"
    stream = container.add_stream("aac", rate=sample_rate, layout=layout)
    frame = av.AudioFrame.from_ndarray(wf.float().cpu().contiguous().numpy(), format="fltp", layout=layout)
    frame.sample_rate = sample_rate
    frame.pts = 0
    return stream, frame


def has_audio(audio):
    waveform = audio.get("waveform") if audio else None
    return waveform is not None and waveform.numel() > 0
