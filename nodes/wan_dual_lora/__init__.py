"""
WAN Dual LoRA Loader Node Package
"""

from .lora_paths import register_folders
from .wan_lora_loader import WANDualLoraLoader

register_folders()

from . import routes  # noqa: E402,F401  (registers the LoRA list / preset API)

__all__ = ["WANDualLoraLoader"]
