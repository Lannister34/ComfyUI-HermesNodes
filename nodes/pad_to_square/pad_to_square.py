import torch.nn.functional as F

from ..common.color import filled, hex_to_rgb


class PadToSquare:
    """Pads an image to a square by adding fill color on the shorter sides, centered."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "size": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 8, "tooltip": "Target square size. 0 = use longest side of input image."}),
            },
            "optional": {
                "fill_color_hex": ("STRING", {"default": "#FFFFFF", "tooltip": "Fill color as hex (#RRGGBB or #RGB)."}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "pad"
    CATEGORY = "hermes/image"
    DESCRIPTION = "Scales the longest side to `size` and centers the image on a square canvas of the fill color."

    def pad(self, image, size=0, fill_color_hex="#FFFFFF"):
        b, h, w, c = image.shape
        if size <= 0:
            size = max(h, w)
        if h == size and w == size:
            return (image,)

        if max(h, w) != size:
            scale = size / max(h, w)
            new_h = min(size, max(1, round(h * scale)))
            new_w = min(size, max(1, round(w * scale)))
            image = F.interpolate(image.movedim(-1, 1), size=(new_h, new_w), mode="bilinear",
                                  align_corners=False, antialias=scale < 1).clamp(0, 1).movedim(1, -1)
            h, w = new_h, new_w

        rgb = hex_to_rgb(fill_color_hex, default=(1.0, 1.0, 1.0))
        result = filled((b, size, size, c), rgb, image.dtype, image.device)
        top, left = (size - h) // 2, (size - w) // 2
        result[:, top:top + h, left:left + w] = image
        return (result,)
