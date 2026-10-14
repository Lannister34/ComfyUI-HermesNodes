import math
from fractions import Fraction

import torch.nn.functional as F
import comfy.utils


class ImageResize:
    """Scales an image so one side hits a target size, keeping aspect and snapping to a multiple."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "size": ("INT", {"default": 720, "min": 64, "max": 8192, "step": 1, "tooltip": "Target length of the side picked by mode."}),
                "mode": (["smallest", "largest"], {"tooltip": "smallest: shorter side >= size (rounded up). largest: longer side <= size (rounded down)."}),
                "multiple_of": ("INT", {"default": 16, "min": 1, "max": 256, "step": 1, "tooltip": "Both output sides are snapped to a multiple of this (16 suits most video models)."}),
                "interpolation": (["lanczos", "bicubic", "bilinear", "nearest"],),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("image", "width", "height")
    FUNCTION = "resize"
    CATEGORY = "hermes/image"
    DESCRIPTION = "Scales an image so its shorter (or longer) side matches a target size, keeping aspect ratio and snapping both sides to a multiple."

    @staticmethod
    def _target_size(w, h, size, mode, multiple_of):
        # smallest: the shorter side reaches size, rounding up; largest: the longer side fits, rounding down
        aspect = Fraction(w, h)
        rounding = math.ceil if mode == "smallest" else math.floor
        width_leads = (w <= h) if mode == "smallest" else (w >= h)

        def snap(value):
            return rounding(Fraction(value) / multiple_of) * multiple_of

        if width_leads:
            new_w = snap(size)
            new_h = snap(new_w / aspect)
        else:
            new_h = snap(size)
            new_w = snap(new_h * aspect)
        return max(new_w, multiple_of), max(new_h, multiple_of)

    def resize(self, image, size, mode, multiple_of, interpolation):
        _, h, w, _ = image.shape
        new_w, new_h = self._target_size(w, h, size, mode, multiple_of)

        samples = image.movedim(-1, 1)  # (B, H, W, C) -> (B, C, H, W)
        if interpolation == "lanczos":
            samples = comfy.utils.lanczos(samples, new_w, new_h)
        elif interpolation == "nearest":
            samples = F.interpolate(samples, size=(new_h, new_w), mode="nearest-exact")
        else:
            samples = F.interpolate(samples, size=(new_h, new_w), mode=interpolation, antialias=True).clamp(0, 1)

        return {"ui": {"text": [f"{w}x{h} -> {new_w}x{new_h}"]}, "result": (samples.movedim(1, -1), new_w, new_h)}
