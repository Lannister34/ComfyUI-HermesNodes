"""
WAN Dual Model Loader Node
Loads both HIGH and LOW WAN models with shared parameters and shift.
"""

import logging
import torch
import folder_paths
import comfy.sd
import comfy.utils
import comfy.model_sampling

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Detect available SageAttention modes
try:
    from sageattention import sageattn, sageattn_qk_int8_pv_fp16_cuda, sageattn_qk_int8_pv_fp8_cuda
    SAGEATTN_MODES = [
        "disabled",
        "sageattn",
        "sageattn_qk_int8_pv_fp16_cuda",
        "sageattn_qk_int8_pv_fp8_cuda",
    ]
    try:
        from sageattention import sageattn_qk_int8_pv_fp16_triton
        SAGEATTN_MODES.append("sageattn_qk_int8_pv_fp16_triton")
    except ImportError:
        pass
except ImportError:
    SAGEATTN_MODES = ["disabled"]


def get_sage_func(mode):
    """Get SageAttention function by mode name."""
    if mode == "sageattn":
        from sageattention import sageattn
        return sageattn
    elif mode == "sageattn_qk_int8_pv_fp16_cuda":
        from sageattention import sageattn_qk_int8_pv_fp16_cuda
        return sageattn_qk_int8_pv_fp16_cuda
    elif mode == "sageattn_qk_int8_pv_fp8_cuda":
        from sageattention import sageattn_qk_int8_pv_fp8_cuda
        return sageattn_qk_int8_pv_fp8_cuda
    elif mode == "sageattn_qk_int8_pv_fp16_triton":
        from sageattention import sageattn_qk_int8_pv_fp16_triton
        return sageattn_qk_int8_pv_fp16_triton
    return None


def apply_shift_to_model(model, shift):
    """Apply shift parameter to model sampling."""
    m = model.clone()

    sampling_base = comfy.model_sampling.ModelSamplingDiscreteFlow
    sampling_type = comfy.model_sampling.CONST

    class ModelSamplingAdvanced(sampling_base, sampling_type):
        pass

    model_sampling = ModelSamplingAdvanced(model.model.model_config)
    model_sampling.set_parameters(shift=shift, multiplier=1000)
    m.add_object_patch("model_sampling", model_sampling)
    return m


def apply_sage_attention(model, sage_mode):
    """Apply SageAttention to model."""
    if sage_mode == "disabled":
        return model

    m = model.clone()
    new_attention = get_sage_func(sage_mode)

    if new_attention is None:
        return model

    def attention_override_sage(func, *args, **kwargs):
        return new_attention.__wrapped__(*args, **kwargs)

    m.set_model_attn1_patch(attention_override_sage)
    m.set_model_attn2_patch(attention_override_sage)

    return m


class WANDualModelLoader:
    DTYPE_MAP = {
        "fp8_e4m3fn": torch.float8_e4m3fn,
        "fp8_e4m3fn_fast": torch.float8_e4m3fn,
        "fp8_e5m2": torch.float8_e5m2,
        "fp16": torch.float16,
        "bf16": torch.bfloat16,
        "fp32": torch.float32
    }

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model_high": (folder_paths.get_filename_list("diffusion_models"), {"tooltip": "The HIGH noise model (handles initial denoising)."}),
                "model_low": (folder_paths.get_filename_list("diffusion_models"), {"tooltip": "The LOW noise model (handles final denoising)."}),
                "clip_name": (folder_paths.get_filename_list("text_encoders"), {"tooltip": "CLIP/T5 text encoder for WAN."}),
                "vae_name": (folder_paths.get_filename_list("vae"), {"tooltip": "VAE for encoding/decoding latents."}),
                "weight_dtype": (["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2", "fp16", "bf16", "fp32"], {"tooltip": "Weight precision for diffusion models."}),
                "compute_dtype": (["default", "fp16", "bf16", "fp32"], {"default": "default", "tooltip": "Compute precision for inference."}),
                "shift": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "tooltip": "Shift parameter for noise schedule. Higher = more denoising in early steps. WAN 2.2 typically uses 8-17."}),
                "sage_attention": (SAGEATTN_MODES, {"default": "disabled", "tooltip": "SageAttention mode for faster inference."}),
            }
        }

    RETURN_TYPES = ("MODEL", "MODEL", "CLIP", "VAE")
    RETURN_NAMES = ("model_high", "model_low", "clip", "vae")
    FUNCTION = "load_models"
    CATEGORY = "loaders"
    DESCRIPTION = "Loads HIGH/LOW WAN models, CLIP, and VAE with shared parameters."

    def load_models(self, model_high, model_low, clip_name, vae_name, weight_dtype, compute_dtype, shift, sage_attention):
        model_options = {}

        # Set weight dtype
        if weight_dtype != "default":
            dtype = self.DTYPE_MAP.get(weight_dtype)
            if dtype:
                model_options["dtype"] = dtype
                logger.info(f"Setting weight dtype to {dtype}")

        if weight_dtype == "fp8_e4m3fn_fast":
            model_options["fp8_optimizations"] = True

        # Load HIGH model
        high_path = folder_paths.get_full_path_or_raise("diffusion_models", model_high)
        high_sd = comfy.utils.load_torch_file(high_path)
        loaded_high = comfy.sd.load_diffusion_model_state_dict(high_sd, model_options=model_options.copy())
        del high_sd

        # Load LOW model
        low_path = folder_paths.get_full_path_or_raise("diffusion_models", model_low)
        low_sd = comfy.utils.load_torch_file(low_path)
        loaded_low = comfy.sd.load_diffusion_model_state_dict(low_sd, model_options=model_options.copy())
        del low_sd

        # Set compute dtype
        if compute_dtype != "default":
            compute_dt = self.DTYPE_MAP.get(compute_dtype)
            if compute_dt:
                loaded_high.set_model_compute_dtype(compute_dt)
                loaded_high.force_cast_weights = False
                loaded_low.set_model_compute_dtype(compute_dt)
                loaded_low.force_cast_weights = False
                logger.info(f"Setting compute dtype to {compute_dt}")

        # Apply shift
        loaded_high = apply_shift_to_model(loaded_high, shift)
        loaded_low = apply_shift_to_model(loaded_low, shift)
        logger.info(f"Applied shift={shift} to both models")

        # Apply SageAttention
        if sage_attention != "disabled":
            loaded_high = apply_sage_attention(loaded_high, sage_attention)
            loaded_low = apply_sage_attention(loaded_low, sage_attention)
            logger.info(f"Applied SageAttention mode: {sage_attention}")

        # Load CLIP (WAN type)
        clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_name)
        clip = comfy.sd.load_clip(
            ckpt_paths=[clip_path],
            embedding_directory=folder_paths.get_folder_paths("embeddings"),
            clip_type=comfy.sd.CLIPType.WAN
        )
        logger.info(f"Loaded CLIP: {clip_name}")

        # Load VAE
        vae_path = folder_paths.get_full_path_or_raise("vae", vae_name)
        vae_sd = comfy.utils.load_torch_file(vae_path)
        vae = comfy.sd.VAE(sd=vae_sd)
        vae.throw_exception_if_invalid()
        logger.info(f"Loaded VAE: {vae_name}")

        return (loaded_high, loaded_low, clip, vae)
