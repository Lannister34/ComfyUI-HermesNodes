"""
WAN Dual LoRA Loader Node
Loads and applies LoRAs to HIGH and LOW WAN models independently
"""

import logging
from typing import Union

import folder_paths
import comfy.utils
import comfy.sd

from .wildcards import process_wildcards

# Logger
logger = logging.getLogger(__name__)


class AnyType(str):
    """A special class that is always equal in not equal comparisons."""

    def __ne__(self, __value: object) -> bool:
        return False


class FlexibleOptionalInputType(dict):
    """A special class to make flexible nodes that accept dynamic inputs."""

    def __init__(self, type, data: Union[dict, None] = None):
        self.type = type
        self.data = data
        if self.data is not None:
            for k, v in self.data.items():
                self[k] = v

    def __getitem__(self, key):
        if self.data is not None and key in self.data:
            return self.data[key]
        return (self.type,)

    def __contains__(self, key):
        return True


any_type = AnyType("*")


def get_lora_list(folder_name):
    """Get list of LoRA files from a folder"""
    try:
        return folder_paths.get_filename_list(folder_name)
    except Exception:
        return []


def parse_lora_name(lora_name, model_type):
    """
    Parse LoRA name with I2V/T2V prefix and return (actual_name, folder_name).
    lora_name: e.g., "I2V/my_lora.safetensors" or "T2V/my_lora.safetensors"
    model_type: 'high' or 'low'
    """
    if lora_name.startswith("I2V/"):
        actual_name = lora_name[4:]
        folder_name = f"wan_loras_i2v_{model_type}"
    elif lora_name.startswith("T2V/"):
        actual_name = lora_name[4:]
        folder_name = f"wan_loras_t2v_{model_type}"
    else:
        # Fallback: try I2V first, then T2V
        actual_name = lora_name
        folder_name = f"wan_loras_i2v_{model_type}"
    return actual_name, folder_name


def load_lora_file(lora_name, model_type):
    """Load a LoRA file and return its state dict"""
    try:
        actual_name, folder_name = parse_lora_name(lora_name, model_type)
        lora_path = folder_paths.get_full_path(folder_name, actual_name)

        # If not found, try the other variant (I2V <-> T2V)
        if lora_path is None and not lora_name.startswith(("I2V/", "T2V/")):
            alt_folder = f"wan_loras_t2v_{model_type}"
            lora_path = folder_paths.get_full_path(alt_folder, actual_name)
            if lora_path:
                folder_name = alt_folder

        # If still not found, try the shared folder
        if lora_path is None:
            if lora_name.startswith("I2V/"):
                shared_folder = "wan_loras_i2v_shared"
            elif lora_name.startswith("T2V/"):
                shared_folder = "wan_loras_t2v_shared"
            else:
                shared_folder = "wan_loras_i2v_shared"  # Default to I2V
            lora_path = folder_paths.get_full_path(shared_folder, actual_name)

            # Try T2V shared if I2V shared didn't work
            if lora_path is None and not lora_name.startswith(("I2V/", "T2V/")):
                lora_path = folder_paths.get_full_path("wan_loras_t2v_shared", actual_name)

        if lora_path is None:
            logger.warning(f"LoRA file not found: {lora_name} in {folder_name}")
            return None
        return comfy.utils.load_torch_file(lora_path, safe_load=True)
    except Exception as e:
        logger.error(f"Error loading LoRA {lora_name}: {e}")
        return None


class WANDualLoraLoader:
    """
    WAN Dual LoRA Loader - Loads LoRAs for both HIGH and LOW WAN models
    with integrated wildcard prompt processing.
    """

    NAME = "WAN Dual LoRA Loader"
    CATEGORY = "loaders/wan"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_high": ("MODEL", {"tooltip": "The HIGH diffusion model"}),
                "model_low": ("MODEL", {"tooltip": "The LOW diffusion model"}),
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
            "hidden": {
                "unique_id": "UNIQUE_ID",
            }
        }

    RETURN_TYPES = ("MODEL", "MODEL", "STRING")
    RETURN_NAMES = ("model_high", "model_low", "prompt")
    FUNCTION = "load_loras"

    def load_loras(self, model_high, model_low, prompt="", seed=0, **kwargs):
        """
        Process HIGH and LOW LoRAs and apply them to respective models.
        Also processes wildcards in the prompt.
        """
        for key, value in kwargs.items():
            key_upper = key.upper()

            # Process HIGH LoRAs
            if key_upper.startswith('HIGH_LORA_'):
                if isinstance(value, dict) and 'on' in value and 'lora' in value and 'strength' in value:
                    if value['on'] and value['strength'] != 0 and value['lora']:
                        lora = load_lora_file(value['lora'], 'high')
                        if lora is not None:
                            model_high, _ = comfy.sd.load_lora_for_models(
                                model_high, None, lora, value['strength'], 0
                            )
                            logger.info(f"Applied HIGH LoRA: {value['lora']} (strength: {value['strength']})")

            # Process LOW LoRAs
            elif key_upper.startswith('LOW_LORA_'):
                if isinstance(value, dict) and 'on' in value and 'lora' in value and 'strength' in value:
                    if value['on'] and value['strength'] != 0 and value['lora']:
                        lora = load_lora_file(value['lora'], 'low')
                        if lora is not None:
                            model_low, _ = comfy.sd.load_lora_for_models(
                                model_low, None, lora, value['strength'], 0
                            )
                            logger.info(f"Applied LOW LoRA: {value['lora']} (strength: {value['strength']})")

        # Process wildcards in prompt
        processed_prompt = process_wildcards(prompt, seed) if prompt else ""

        return (model_high, model_low, processed_prompt)

    @classmethod
    def get_lora_lists(cls):
        """Get available LoRA lists for HIGH and LOW"""
        return {
            'high': get_lora_list('wan_loras_high'),
            'low': get_lora_list('wan_loras_low')
        }
