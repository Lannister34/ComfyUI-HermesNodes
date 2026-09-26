"""
Hermes Nodes - ComfyUI custom nodes for WAN 2.2 workflows, image prep and in-graph video preview.
https://github.com/Lannister34/ComfyUI-HermesNodes
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
