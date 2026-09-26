import torch


def hex_to_rgb(hex_str, default=(0.0, 0.0, 0.0)):
    """'#RRGGBB' or '#RGB' -> (r, g, b) floats in 0..1. Invalid input returns `default`."""
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return default
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return default


def filled(shape, rgb, dtype, device):
    """Tensor of `shape` (..., C) filled with an RGB color. A 4th (alpha) channel is set opaque."""
    color = torch.tensor((*rgb, 1.0)[:shape[-1]], dtype=dtype, device=device)
    return color.expand(shape).clone()
