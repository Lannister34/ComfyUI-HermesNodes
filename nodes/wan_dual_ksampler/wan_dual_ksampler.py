"""
WAN Dual KSampler Node
Samples using HIGH model first, then LOW model for WAN 2.2 MoE architecture.
"""

import torch
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview


class WANDualKSampler:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model_high": ("MODEL", {"tooltip": "The HIGH noise model (handles initial denoising steps)."}),
                "model_low": ("MODEL", {"tooltip": "The LOW noise model (handles final denoising steps)."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True, "tooltip": "The random seed used for creating the noise."}),
                "steps": ("INT", {"default": 8, "min": 1, "max": 10000, "tooltip": "Total number of denoising steps."}),
                "switch_step": ("INT", {"default": 4, "min": 1, "max": 10000, "tooltip": "Step at which to switch from HIGH to LOW model."}),
                "cfg": ("FLOAT", {"default": 6.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01, "tooltip": "Classifier-Free Guidance scale."}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"tooltip": "The sampling algorithm to use."}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"tooltip": "The scheduler for noise removal."}),
                "positive": ("CONDITIONING", {"tooltip": "Positive conditioning (prompt)."}),
                "negative": ("CONDITIONING", {"tooltip": "Negative conditioning."}),
                "latent_image": ("LATENT", {"tooltip": "The latent image to denoise."}),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Denoising strength."}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)
    OUTPUT_TOOLTIPS = ("The denoised latent.",)
    FUNCTION = "sample"
    CATEGORY = "sampling"
    DESCRIPTION = "Dual KSampler for WAN 2.2 MoE: runs HIGH model for initial steps, then LOW model for remaining steps."

    def sample(self, model_high, model_low, seed, steps, switch_step, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise=1.0):
        # Ensure switch_step is valid
        switch_step = min(switch_step, steps)

        latent = latent_image["samples"]
        latent = comfy.sample.fix_empty_latent_channels(model_high, latent)

        # Prepare noise
        batch_inds = latent_image["batch_index"] if "batch_index" in latent_image else None
        noise = comfy.sample.prepare_noise(latent, seed, batch_inds)

        noise_mask = latent_image.get("noise_mask", None)

        # Phase 1: HIGH model (steps 0 to switch_step)
        callback_high = latent_preview.prepare_callback(model_high, steps)
        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

        samples = comfy.sample.sample(
            model_high, noise, steps, cfg, sampler_name, scheduler,
            positive, negative, latent,
            denoise=denoise,
            disable_noise=False,
            start_step=0,
            last_step=switch_step,
            force_full_denoise=False,  # Keep noise for LOW model
            noise_mask=noise_mask,
            callback=callback_high,
            disable_pbar=disable_pbar,
            seed=seed
        )

        # Phase 2: LOW model (steps switch_step to end)
        if switch_step < steps:
            callback_low = latent_preview.prepare_callback(model_low, steps)

            samples = comfy.sample.sample(
                model_low, noise, steps, cfg, sampler_name, scheduler,
                positive, negative, samples,
                denoise=denoise,
                disable_noise=True,  # Don't add new noise, continue from HIGH output
                start_step=switch_step,
                last_step=steps,
                force_full_denoise=True,
                noise_mask=noise_mask,
                callback=callback_low,
                disable_pbar=disable_pbar,
                seed=seed
            )

        out = latent_image.copy()
        out["samples"] = samples
        return (out,)
