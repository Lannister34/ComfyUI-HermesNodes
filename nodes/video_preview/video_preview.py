"""
Video Preview Node - shows a single video with a click-to-pause player.
Can optionally save to output/ or just preview from temp/.
"""

import logging

from ..common.video import CODECS, encode_mp4, has_audio, output_target, to_uint8_frames, workflow_metadata

logger = logging.getLogger(__name__)


class VideoPreview:
    TEMP_PREFIX = "hermes_video_preview"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("IMAGE", {"tooltip": "Video frames (IMAGE batch)."}),
                "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5, "tooltip": "Playback FPS."}),
                "filename_prefix": ("STRING", {"default": "VideoPreview", "tooltip": "Filename prefix. Supports subfolders like 'previews/run1'."}),
                "save_output": ("BOOLEAN", {"default": False, "tooltip": "Save permanently to output/ folder. Off = preview-only (temp/)."}),
                "crf": ("INT", {"default": 18, "min": 0, "max": 51, "step": 1, "tooltip": "h264 quality (lower = better, 18 is visually lossless). Used as 'cq' on NVENC."}),
                "codec": (CODECS, {"default": "auto", "tooltip": "auto picks NVENC when available: same speed as libx264 'fast' on real footage, but it leaves the CPU free. Falls back to libx264 if the driver refuses."}),
            },
            "optional": {
                "audio": ("AUDIO", {"tooltip": "Optional audio track to mux into the video."}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "width", "height", "filepath")
    OUTPUT_TOOLTIPS = ("The input frames, unchanged.", "Frame width.", "Frame height.",
                       "Absolute path of the written mp4.")
    FUNCTION = "preview"
    CATEGORY = "hermes/video"
    OUTPUT_NODE = True
    DESCRIPTION = "Encodes frames to mp4 and plays them in the node: autoplay, sound on hover, click to pause."

    def preview(self, video, fps, filename_prefix="VideoPreview", save_output=False, crf=18,
                codec="auto", audio=None, prompt=None, extra_pnginfo=None):
        _, height, width, _ = video.shape
        out_path, ui_entry = output_target(filename_prefix, save_output, width, height, self.TEMP_PREFIX)

        frames = to_uint8_frames(video)
        logger.debug("[Hermes] %s: encoding %s frames at %s fps (crf=%s, audio=%s) -> %s",
                     type(self).__name__, frames.shape, fps, crf, has_audio(audio), out_path)
        try:
            encode_mp4(frames, float(fps), out_path, crf=crf, codec=codec, audio=audio,
                       metadata=workflow_metadata(prompt, extra_pnginfo))
        except Exception:
            if save_output:
                raise
            # a failed preview must not stop the frames flowing to downstream nodes
            logger.exception("[Hermes] %s: preview encoding failed", type(self).__name__)
            return {"ui": {}, "result": (video, width, height, "")}

        ui_entry["fps"] = float(fps)
        return {"ui": {"videos": [ui_entry]}, "result": (video, width, height, out_path)}
