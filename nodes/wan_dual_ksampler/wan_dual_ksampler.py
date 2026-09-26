"""
WAN Dual KSampler Nodes
Sample with the HIGH noise model first, then the LOW noise model (WAN 2.2 MoE architecture).
"""

import gc
import logging
import time

import torch
import comfy.model_management
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview

logger = logging.getLogger(__name__)


def _free_vram():
    comfy.model_management.unload_all_models()
    gc.collect()
    comfy.model_management.soft_empty_cache(force=True)


def _run_phase(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent,
               denoise, start_step, last_step, noise_mask, batch_inds, first):
    """One KSamplerAdvanced-style pass over [start_step, last_step).

    The first phase adds noise and leaves the result noisy for the second one; the second
    phase continues from that latent with noise disabled and fully denoises.
    """
    # fix channels before preparing noise, so the noise matches the model (as KSamplerAdvanced does)
    latent = comfy.sample.fix_empty_latent_channels(model, latent)
    if first:
        noise = comfy.sample.prepare_noise(latent, seed, batch_inds)
    else:
        noise = torch.zeros(latent.size(), dtype=latent.dtype, layout=latent.layout, device="cpu")

    return comfy.sample.sample(
        model, noise, steps, cfg, sampler_name, scheduler,
        positive, negative, latent,
        denoise=denoise,
        disable_noise=not first,
        start_step=start_step,
        last_step=last_step,
        force_full_denoise=not first,
        noise_mask=noise_mask,
        callback=latent_preview.prepare_callback(model, steps),
        disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
        seed=seed,
    )


def _dual_sample(model_high, model_low, seed, steps, switch_step, high_cfg, low_cfg, sampler_name,
                 scheduler, positive, negative, latent_image, denoise, between_phases=None):
    """HIGH model for steps [0, switch_step), LOW model for [switch_step, steps)."""
    noise_mask = latent_image.get("noise_mask")
    batch_inds = latent_image.get("batch_index")
    common = dict(seed=seed, steps=steps, sampler_name=sampler_name, scheduler=scheduler,
                  positive=positive, negative=negative, denoise=denoise,
                  noise_mask=noise_mask, batch_inds=batch_inds)

    t0 = time.perf_counter()
    samples = _run_phase(model_high, cfg=high_cfg, latent=latent_image["samples"],
                         start_step=0, last_step=switch_step, first=True, **common)
    high_time = time.perf_counter() - t0

    if between_phases is not None:
        between_phases()

    low_time = 0.0
    if switch_step < steps:
        t0 = time.perf_counter()
        samples = _run_phase(model_low, cfg=low_cfg, latent=samples,
                             start_step=switch_step, last_step=steps, first=False, **common)
        low_time = time.perf_counter() - t0

    logger.info("[Hermes] WAN Dual KSampler: HIGH %d steps %.1fs, LOW %d steps %.1fs",
                switch_step, high_time, steps - switch_step, low_time)

    out = latent_image.copy()
    out["samples"] = samples
    return (out,)


class WANDualKSampler:
    """Step-based dual model sampler for WAN 2.2 MoE architecture."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_high": ("MODEL", {"tooltip": "The HIGH noise model (handles initial denoising steps)."}),
                "model_low": ("MODEL", {"tooltip": "The LOW noise model (handles final denoising steps)."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True, "tooltip": "The random seed used for creating the noise."}),
                "steps": ("INT", {"default": 8, "min": 1, "max": 10000, "tooltip": "Total number of denoising steps."}),
                "switch_step": ("INT", {"default": 4, "min": 1, "max": 10000, "tooltip": "Step at which to switch from HIGH to LOW model."}),
                "first_cfg": ("FLOAT", {"default": 6.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01, "tooltip": "CFG scale for HIGH model phase."}),
                "second_cfg": ("FLOAT", {"default": 6.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01, "tooltip": "CFG scale for LOW model phase."}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"tooltip": "The sampling algorithm to use."}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"tooltip": "The scheduler for noise removal."}),
                "positive": ("CONDITIONING", {"tooltip": "Positive conditioning (prompt)."}),
                "negative": ("CONDITIONING", {"tooltip": "Negative conditioning."}),
                "latent_image": ("LATENT", {"tooltip": "The latent image to denoise."}),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Denoising strength."}),
                "offload_between_phases": ("BOOLEAN", {"default": False, "tooltip": "Unload models from VRAM between the HIGH and LOW phases and again after sampling. Helps on low-VRAM GPUs at the cost of reload time."}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)
    OUTPUT_TOOLTIPS = ("The denoised latent.",)
    FUNCTION = "sample"
    CATEGORY = "sampling"
    DESCRIPTION = "Dual KSampler for WAN 2.2 MoE: runs HIGH model for initial steps, then LOW model for remaining steps."

    def sample(self, model_high, model_low, seed, steps, switch_step, first_cfg, second_cfg, sampler_name,
               scheduler, positive, negative, latent_image, denoise=1.0, offload_between_phases=False):
        result = _dual_sample(
            model_high, model_low, seed, steps, min(switch_step, steps), first_cfg, second_cfg,
            sampler_name, scheduler, positive, negative, latent_image, denoise,
            between_phases=_free_vram if offload_between_phases else comfy.model_management.soft_empty_cache,
        )
        if offload_between_phases:
            _free_vram()
        return result


class WANDualKSamplerBeta:
    """Boundary-based dual model sampler for WAN 2.2 MoE architecture.

    Uses a timestep boundary (0.875 for T2V, 0.9 for I2V) to decide when to switch
    models, matching the MoE training configuration.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_high": ("MODEL", {"tooltip": "The HIGH noise model (handles high noise levels, t > boundary)."}),
                "model_low": ("MODEL", {"tooltip": "The LOW noise model (handles low noise levels, t < boundary)."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True, "tooltip": "The random seed used for creating the noise."}),
                "steps": ("INT", {"default": 20, "min": 1, "max": 10000, "tooltip": "Total number of denoising steps."}),
                "boundary": ("FLOAT", {"default": 0.875, "min": 0.0, "max": 1.0, "step": 0.001, "round": 0.001, "tooltip": "Timestep boundary for model switching. Recommended: 0.875 for T2V, 0.9 for I2V."}),
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
    DESCRIPTION = "Boundary-based Dual KSampler for WAN 2.2 MoE: switches from HIGH to LOW model based on timestep boundary."

    @staticmethod
    def _switch_step(model, scheduler, steps, boundary):
        """First step whose timestep (0..1) falls below the boundary; `steps` if none does."""
        sampling = model.get_model_object("model_sampling")
        sigmas = comfy.samplers.calculate_sigmas(sampling, scheduler, steps)
        for i, sigma in enumerate(sigmas.tolist()[1:], start=1):
            if sampling.timestep(sigma) / 1000 < boundary:
                return i
        return steps

    def sample(self, model_high, model_low, seed, steps, boundary, cfg, sampler_name, scheduler,
               positive, negative, latent_image, denoise=1.0):
        switch_step = self._switch_step(model_high, scheduler, steps, boundary)
        logger.info("[Hermes] WAN Dual KSampler (Boundary): boundary=%s -> switching at step %d/%d",
                    boundary, switch_step, steps)
        return _dual_sample(model_high, model_low, seed, steps, switch_step, cfg, cfg, sampler_name,
                            scheduler, positive, negative, latent_image, denoise)
