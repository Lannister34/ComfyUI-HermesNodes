import sys
from dataclasses import dataclass

import av
import numpy as np
import torch

from .timeline import audio_window, frames_from, overlaps, resample_frames, silence

CHANNEL_LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1"}


@dataclass(frozen=True)
class LoadedVideo:
    frames: torch.Tensor
    audio: dict
    fps: float
    has_audio: bool


def load_video(path: str, fps: float, start_time: float, max_frames: int) -> LoadedVideo:
    try:
        frames, out_fps, first_shown = _read_frames(path, fps, start_time, max_frames)
        duration = frames.shape[0] / out_fps
        audio = _read_audio(path, first_shown, duration)
    except av.FFmpegError as e:
        raise ValueError(f"Load Video: cannot read {path}: {e}") from e
    return LoadedVideo(frames=frames, audio=audio if audio is not None else silence(duration),
                       fps=out_fps, has_audio=audio is not None)


def _read_frames(path: str, fps: float, start_time: float, max_frames: int) -> tuple[torch.Tensor, float, float]:
    limit = max_frames if max_frames > 0 else sys.maxsize
    with av.open(path) as container:
        if not container.streams.video:
            raise ValueError(f"Load Video: {path} has no video stream")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        source_fps = float(stream.average_rate or stream.guessed_rate or 0)
        if fps <= 0 and source_fps <= 0:
            raise ValueError(f"Load Video: {path} does not state its frame rate; set fps explicitly")
        out_fps = fps if fps > 0 else source_fps
        origin = float(stream.start_time * stream.time_base) if stream.start_time is not None else 0.0
        first_time = origin + start_time
        if start_time > 0:
            container.seek(int(first_time / stream.time_base), stream=stream, backward=True)

        decoded = ((frame.time, frame) for frame in container.decode(stream) if frame.time is not None)
        picked = resample_frames(decoded, first_time, out_fps, limit, 1.0 / (source_fps or out_fps)) \
            if fps > 0 else frames_from(decoded, first_time, limit)
        chunks = []
        first_shown = None
        for time, frame in picked:
            if first_shown is None:
                first_shown = first_time if fps > 0 else time
            chunks.append(torch.from_numpy(frame.to_ndarray(format="rgb24")))
    if not chunks:
        raise ValueError(f"Load Video: no frames in {path} from {start_time:.3f}s on")
    return torch.stack(chunks).float().div_(255.0), out_fps, first_shown


def _read_audio(path: str, window_start: float, duration: float) -> dict | None:
    with av.open(path) as container:
        if not container.streams.audio:
            return None
        stream = container.streams.audio[0]
        sample_rate = stream.rate or stream.codec_context.sample_rate
        layout = CHANNEL_LAYOUTS.get(stream.channels, "stereo")
        if window_start > 1:
            container.seek(int((window_start - 1) / stream.time_base), stream=stream, backward=True)
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=sample_rate)
        window_end = window_start + duration
        pieces = []
        samples_start = None
        for frame in container.decode(stream):
            if samples_start is None:
                if frame.time is None:
                    continue
                samples_start = float(frame.time)
            for converted in resampler.resample(frame):
                pieces.append(converted.to_ndarray())
            if frame.time is not None and frame.time > window_end:
                break
        for converted in resampler.resample(None):
            pieces.append(converted.to_ndarray())
    if not pieces:
        return None
    samples = torch.from_numpy(np.concatenate(pieces, axis=1).astype(np.float32))
    if not overlaps(samples.shape[1], sample_rate, samples_start, window_start, duration):
        return None
    waveform = audio_window(samples, sample_rate, samples_start, window_start, duration)
    return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}
