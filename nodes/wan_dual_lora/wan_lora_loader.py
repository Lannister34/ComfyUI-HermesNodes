"""
WAN Dual LoRA Loader Node
Loads and applies LoRAs to HIGH and LOW WAN models independently.
"""

import logging

import comfy.sd
import comfy.utils

from .lora_paths import resolve_lora_path
from .wildcards import process_wildcards

logger = logging.getLogger(__name__)


class AnyType(str):
    """A type string that matches any other type in ComfyUI's link validation."""

    def __ne__(self, __value: object) -> bool:
        return False


class FlexibleOptionalInputType(dict):
    """Optional-inputs dict that accepts any key, so the front end can add LoRA rows dynamically."""

    def __init__(self, type, data=None):
        super().__init__(data or {})
        self.type = type

    def __getitem__(self, key):
        if key in self.keys():
            return super().__getitem__(key)
        return (self.type,)

    def __contains__(self, key):
        return True


any_type = AnyType("*")


def _enabled_loras(kwargs, prefix):
    """Yield (name, strength) for every enabled, non-zero LoRA row whose input key starts with prefix."""
    for key, value in kwargs.items():
        if not key.upper().startswith(prefix):
            continue
        if not (isinstance(value, dict) and {"on", "lora", "strength"} <= value.keys()):
            continue
        if value["on"] and value["lora"] and value["strength"] != 0:
            yield value["lora"], value["strength"]


class WANDualLoraLoader:
    """
    Loads LoRAs for both HIGH and LOW WAN 2.2 models, with integrated wildcard prompt processing.
    LoRA rows are added by the front end as dynamic optional inputs: HIGH_LORA_n / LOW_LORA_n,
    each a dict {"on": bool, "lora": "<I2V|T2V>/<file>", "strength": float}.
    """

    CATEGORY = "loaders/wan"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_high": ("MODEL", {"tooltip": "The HIGH noise diffusion model"}),
                "model_low": ("MODEL", {"tooltip": "The LOW noise diffusion model"}),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Enter prompt with optional wildcards: {option1|option2} or __wildcard__"
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xffffffffffffffff,
                    "tooltip": "Seed for wildcard randomization"
                }),
            },
            "optional": FlexibleOptionalInputType(type=any_type),
        }

    RETURN_TYPES = ("MODEL", "MODEL", "STRING")
    RETURN_NAMES = ("model_high", "model_low", "prompt")
    OUTPUT_TOOLTIPS = ("HIGH model with its LoRAs applied.", "LOW model with its LoRAs applied.",
                       "Prompt with wildcards resolved.")
    FUNCTION = "load_loras"
    DESCRIPTION = "Applies separate LoRA stacks to the WAN 2.2 HIGH and LOW noise models, with presets and wildcard prompts."

    @staticmethod
    def _apply(model, loras, model_type):
        for name, strength in loras:
            path = resolve_lora_path(name, model_type)
            if path is None:
                logger.warning("[Hermes] %s LoRA not found, skipped: %s", model_type.upper(), name)
                continue
            lora = comfy.utils.load_torch_file(path, safe_load=True)
            model, _ = comfy.sd.load_lora_for_models(model, None, lora, strength, 0)
            logger.debug("[Hermes] Applied %s LoRA %s (strength %s)", model_type.upper(), name, strength)
        return model

    def load_loras(self, model_high, model_low, prompt="", seed=0, **kwargs):
        model_high = self._apply(model_high, _enabled_loras(kwargs, "HIGH_LORA_"), "high")
        model_low = self._apply(model_low, _enabled_loras(kwargs, "LOW_LORA_"), "low")
        processed_prompt = process_wildcards(prompt, seed) if prompt else ""
        return (model_high, model_low, processed_prompt)
