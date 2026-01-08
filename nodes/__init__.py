"""
Hermes Nodes - Node packages
"""

from .wan_dual_lora import WANDualLoraLoader, preset_manager
from .wan_dual_ksampler import WANDualKSampler

__all__ = ["WANDualLoraLoader", "preset_manager", "WANDualKSampler"]
