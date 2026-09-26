"""
Video Compare Node - tiles up to six videos into one grid clip for side-by-side comparison
(e.g. LoRA or sampler A/B tests), with an in-node click-to-pause player.
"""

import logging
import math

import torch
import torch.nn.functional as F

from ..common.color import filled, hex_to_rgb
from ..common.video import encode_mp4, output_target, to_uint8_frames, workflow_metadata

logger = logging.getLogger(__name__)


class VideoCompare:
    MAX_VIDEOS = 6
    TEMP_PREFIX = "hermes_video_compare"

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5, "tooltip": "Playback FPS."}),
                "layout": (["auto_grid", "row", "column"], {"default": "auto_grid", "tooltip": "auto_grid: fill square first, then add columns. row: horizontal line. column: vertical stack."}),
                "gap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 1, "tooltip": "Gap in pixels between videos."}),
                "gap_color": ("STRING", {"default": "#000000", "tooltip": "Gap color as hex. Also fills empty cells in grid."}),
                "match_mode": (["resize", "pad"], {"default": "resize", "tooltip": "resize: scale into the cell keeping aspect, pad the rest. pad: no scaling, center-pad or crop to the cell."}),
                "frame_mode": (["shortest", "longest"], {"default": "shortest", "tooltip": "shortest: trim to shortest. longest: hold last frame of shorter videos."}),
                "filename_prefix": ("STRING", {"default": "VideoCompare", "tooltip": "Filename prefix. Supports subfolders like 'comparisons/v1_vs_v2'."}),
                "save_output": ("BOOLEAN", {"default": False, "tooltip": "Save permanently to output/ folder. Off = preview-only (temp/)."}),
                "crf": ("INT", {"default": 18, "min": 0, "max": 51, "step": 1, "tooltip": "h264 quality (lower = better, 18 is visually lossless)."}),
            },
            "optional": {
                f"video_{i}": ("IMAGE", {"tooltip": f"Optional video #{i}. Any unconnected slot is skipped."})
                for i in range(1, cls.MAX_VIDEOS + 1)
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }
        return inputs

    RETURN_TYPES = ("IMAGE", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "width", "height", "filepath")
    OUTPUT_TOOLTIPS = ("The tiled grid frames.", "Grid width.", "Grid height.",
                       "Absolute path of the written mp4.")
    FUNCTION = "compare"
    CATEGORY = "hermes/video"
    OUTPUT_NODE = True
    DESCRIPTION = "Tiles up to six videos into one grid clip for side-by-side comparison."

    @staticmethod
    def _compute_grid(n, layout):
        """(cols, rows) for n videos."""
        if layout == "row":
            return n, 1
        if layout == "column":
            return 1, n
        cols = math.ceil(math.sqrt(n))
        return cols, math.ceil(n / cols)

    @staticmethod
    def _align_frames(videos, frame_mode):
        lengths = [v.shape[0] for v in videos]
        if frame_mode == "shortest":
            target = min(lengths)
            return [v[:target] for v in videos]
        target = max(lengths)
        return [
            torch.cat([v, v[-1:].expand(target - v.shape[0], -1, -1, -1)], dim=0) if v.shape[0] < target else v
            for v in videos
        ]

    @staticmethod
    def _pad_to_size(video, target_h, target_w, rgb):
        """Center-pad (or center-crop) frames to exactly (target_h, target_w)."""
        f, h, w, c = video.shape
        if h > target_h:
            top = (h - target_h) // 2
            video = video[:, top:top + target_h]
            h = target_h
        if w > target_w:
            left = (w - target_w) // 2
            video = video[:, :, left:left + target_w]
            w = target_w
        if h == target_h and w == target_w:
            return video
        out = filled((f, target_h, target_w, c), rgb, video.dtype, video.device)
        top, left = (target_h - h) // 2, (target_w - w) // 2
        out[:, top:top + h, left:left + w] = video
        return out

    def _fit_to_cell(self, video, target_h, target_w, rgb, mode):
        _, h, w, _ = video.shape
        if (h, w) == (target_h, target_w):
            return video
        if mode == "resize":
            scale = min(target_w / w, target_h / h)
            new_h, new_w = max(1, round(h * scale)), max(1, round(w * scale))
            video = F.interpolate(video.movedim(-1, 1), size=(new_h, new_w), mode="bicubic",
                                  antialias=True).clamp(0, 1).movedim(1, -1)
        return self._pad_to_size(video, target_h, target_w, rgb)

    def compare(self, fps, layout, gap, gap_color, match_mode, frame_mode, filename_prefix="VideoCompare",
                save_output=False, crf=18, prompt=None, extra_pnginfo=None, **kwargs):
        videos = [kwargs[f"video_{i}"] for i in range(1, self.MAX_VIDEOS + 1) if kwargs.get(f"video_{i}") is not None]
        if not videos:
            raise ValueError("Video Compare: no videos connected. Connect at least one video_N input.")

        ref = videos[0]
        videos = [v.to(dtype=ref.dtype, device=ref.device) for v in videos]
        channels = min(v.shape[-1] for v in videos)
        videos = self._align_frames([v[..., :channels] for v in videos], frame_mode)

        rgb = hex_to_rgb(gap_color)
        n = len(videos)
        cols, rows = self._compute_grid(n, layout)
        cell_h = max(v.shape[1] for v in videos)
        cell_w = max(v.shape[2] for v in videos)
        cells = [self._fit_to_cell(v, cell_h, cell_w, rgb, match_mode) for v in videos]
        num_frames = cells[0].shape[0]

        def blank(h, w):
            return filled((num_frames, h, w, channels), rgb, ref.dtype, ref.device)

        grid_rows = []
        for r in range(rows):
            pieces = []
            for col in range(cols):
                idx = r * cols + col
                pieces.append(cells[idx] if idx < n else blank(cell_h, cell_w))
                if gap > 0 and col < cols - 1:
                    pieces.append(blank(cell_h, gap))
            grid_rows.append(torch.cat(pieces, dim=2))
            if gap > 0 and r < rows - 1:
                grid_rows.append(blank(gap, grid_rows[-1].shape[2]))
        out = torch.cat(grid_rows, dim=1)
        out_h, out_w = out.shape[1], out.shape[2]

        out_path, ui_entry = output_target(filename_prefix, save_output, out_w, out_h, self.TEMP_PREFIX)
        frames = to_uint8_frames(out[..., :3])
        logger.debug("[Hermes] VideoCompare: encoding %s frames at %s fps (crf=%s) -> %s",
                     frames.shape, fps, crf, out_path)
        try:
            encode_mp4(frames, float(fps), out_path, crf=crf, codec="libx264",
                       metadata=workflow_metadata(prompt, extra_pnginfo))
        except Exception:
            if save_output:
                raise
            logger.exception("[Hermes] VideoCompare: preview encoding failed")
            return {"ui": {}, "result": (out, out_w, out_h, "")}

        ui_entry["fps"] = float(fps)
        return {"ui": {"videos": [ui_entry]}, "result": (out, out_w, out_h, out_path)}
