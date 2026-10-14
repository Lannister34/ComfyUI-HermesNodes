"""
Hermes Nodes - node registry.
"""

from .wan_dual_lora import WANDualLoraLoader
from .wan_dual_ksampler import WANDualKSampler, WANDualKSamplerBeta
from .image_resize import ImageResize
from .pad_to_square import PadToSquare
from .random_image_loader import RandomImageLoader
from .video_preview import VideoPreview
from .video_player import VideoPlayer
from .video_compare import VideoCompare
from .video_loader import LoadVideo

NODE_CLASS_MAPPINGS = {
    # WAN 2.2
    "WANDualLoraLoader": WANDualLoraLoader,
    "WANDualKSampler": WANDualKSampler,
    "WANDualKSamplerBeta": WANDualKSamplerBeta,
    # Image
    "HermesImageResize": ImageResize,
    "HermesPadToSquare": PadToSquare,
    "HermesRandomImageLoader": RandomImageLoader,
    # Video
    "HermesVideoPreview": VideoPreview,
    "HermesVideoPlayer": VideoPlayer,
    "HermesVideoCompare": VideoCompare,
    "HermesLoadVideo": LoadVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WANDualLoraLoader": "WAN Dual LoRA Loader",
    "WANDualKSampler": "WAN Dual KSampler",
    "WANDualKSamplerBeta": "WAN Dual KSampler (Boundary)",
    "HermesImageResize": "Image Scale To",
    "HermesPadToSquare": "Pad Image to Square",
    "HermesRandomImageLoader": "Random Image Loader",
    "HermesVideoPreview": "Video Preview",
    "HermesVideoPlayer": "Video Player",
    "HermesVideoCompare": "Video Compare (Side-by-Side)",
    "HermesLoadVideo": "Load Video (Resampled)",
}
