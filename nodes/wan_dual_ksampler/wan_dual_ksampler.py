"""
WAN Dual KSampler Nodes
Sample with the HIGH noise model first, then the LOW noise model (WAN 2.2 MoE architecture).
"""

import gc
import inspect
import logging
import time

import torch
import comfy.model_management
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview

logger = logging.getLogger(__name__)

_prepare_empty_noise = getattr(comfy.sample, "prepare_empty_noise", None)
_FIX_CHANNELS_TAKES_RATIOS = (
    "downscale_ratio_spacial" in inspect.signature(comfy.sample.fix_empty_latent_channels).parameters
)


def _free_vram():
    comfy.model_management.unload_all_models()
    gc.collect()
    comfy.model_management.soft_empty_cache(force=True)


def _empty_noise(samples):
    """Zero noise for a phase that continues an already noised latent; nested-latent aware where core is."""
    if _prepare_empty_noise is not None:
        return _prepare_empty_noise(samples)
    return torch.zeros(samples.size(), dtype=samples.dtype, layout=samples.layout, device="cpu")


def _fix_channels(model, samples, latent_image):
    if _FIX_CHANNELS_TAKES_RATIOS:
        return comfy.sample.fix_empty_latent_channels(
            model, samples, latent_image.get("downscale_ratio_spacial"), latent_image.get("downscale_ratio_temporal")
        )
    return comfy.sample.fix_empty_latent_channels(model, samples)


def _phase_plan(steps, switch_step):
    """[("high" | "low", first_step, last_step)] for a HIGH -> LOW run; either phase may be empty.

    The phase that starts at step 0 adds the noise and the one that ends at `steps` denoises
    fully; a phase that ends earlier hands its leftover noise on, as KSamplerAdvanced does.
    """
    switch_step = max(0, min(switch_step, steps))
    plan = []
    if switch_step > 0:
        plan.append(("high", 0, switch_step))
    if switch_step < steps:
        plan.append(("low", switch_step, steps))
    return plan


def _run_phase(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, samples,
               denoise, start_step, last_step, latent_image):
    """One KSamplerAdvanced-style pass over [start_step, last_step)."""
    add_noise = start_step == 0
    # fix channels before preparing noise, so the noise matches the model (as KSamplerAdvanced does)
    samples = _fix_channels(model, samples, latent_image)
    if add_noise:
        noise = comfy.sample.prepare_noise(samples, seed, latent_image.get("batch_index"))
    else:
        noise = _empty_noise(samples)

    return comfy.sample.sample(
        model, noise, steps, cfg, sampler_name, scheduler,
        positive, negative, samples,
        denoise=denoise,
        disable_noise=not add_noise,
        start_step=start_step,
        last_step=last_step,
        force_full_denoise=last_step >= steps,
        noise_mask=latent_image.get("noise_mask"),
        callback=latent_preview.prepare_callback(model, steps),
        disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
        seed=seed,
    )


def _dual_sample(model_high, model_low, seed, steps, switch_step, high_cfg, low_cfg, sampler_name,
                 scheduler, positive, negative, latent_image, denoise, between_phases=None):
    """HIGH model for steps [0, switch_step), LOW model for [switch_step, steps)."""
    phases = {"high": (model_high, high_cfg), "low": (model_low, low_cfg)}
    samples = latent_image["samples"]
    step_counts = {"high": 0, "low": 0}
    seconds = {"high": 0.0, "low": 0.0}
    for i, (which, start, last) in enumerate(_phase_plan(steps, switch_step)):
        if i > 0 and between_phases is not None:
            between_phases()
        model, cfg = phases[which]
        t0 = time.perf_counter()
        samples = _run_phase(model, seed, steps, cfg, sampler_name, scheduler, positive, negative,
                             samples, denoise, start, last, latent_image)
        seconds[which] = time.perf_counter() - t0
        step_counts[which] = last - start

    logger.info("[Hermes] WAN Dual KSampler: HIGH %d steps %.1fs, LOW %d steps %.1fs",
                step_counts["high"], seconds["high"], step_counts["low"], seconds["low"])

    out = latent_image.copy()
    out.pop("downscale_ratio_spacial", None)
    out.pop("downscale_ratio_temporal", None)
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
            model_high, model_low, seed, steps, switch_step, first_cfg, second_cfg,
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
    def _switch_step(model, sampler_name, scheduler, steps, boundary, denoise=1.0):
        """First step that starts at a timestep (0..1) below the boundary: `steps` if none does, 0 if all do.

        Read off the schedule the run will actually use, KSampler's own: the denoise tail, and the
        discarded penultimate sigma of dpm_2 and uni_pc, both move the crossing.
        """
        sampling = model.get_model_object("model_sampling")
        sigmas = comfy.samplers.KSampler(model, steps=steps, device="cpu", sampler=sampler_name,
                                         scheduler=scheduler, denoise=denoise).sigmas
        for i, sigma in enumerate(sigmas[:-1]):
            if float(sampling.timestep(sigma)) / 1000 < boundary:
                return i
        return steps

    def sample(self, model_high, model_low, seed, steps, boundary, cfg, sampler_name, scheduler,
               positive, negative, latent_image, denoise=1.0):
        switch_step = self._switch_step(model_high, sampler_name, scheduler, steps, boundary, denoise)
        logger.info("[Hermes] WAN Dual KSampler (Boundary): boundary=%s -> switching at step %d/%d",
                    boundary, switch_step, steps)
        return _dual_sample(model_high, model_low, seed, steps, switch_step, cfg, cfg, sampler_name,
                            scheduler, positive, negative, latent_image, denoise)
