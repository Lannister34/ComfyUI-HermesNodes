"""
WAN Dual KSampler Node
Samples using HIGH model first, then LOW model for WAN 2.2 MoE architecture.
"""

import gc
import time
import torch
import comfy.sample
import comfy.samplers
import comfy.utils
import comfy.model_management
import latent_preview

# Try to import timing module for database logging
try:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
    from timing import record_node, get_current_run_id
    TIMING_AVAILABLE = True
except ImportError:
    TIMING_AVAILABLE = False

# Import hybrid step tracking for sageattn3_hybrid mode
try:
    from ..wan_dual_model_loader import set_hybrid_step
    HYBRID_AVAILABLE = True
except ImportError:
    HYBRID_AVAILABLE = False
    def set_hybrid_step(current_step, total_steps, switch_step=0):
        pass


class WANDualKSampler:
    """Step-based dual model sampler for WAN 2.2 MoE architecture."""

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
                "offload_between_phases": ("BOOLEAN", {"default": False, "tooltip": "Offload HIGH model before running LOW model. May improve LOW performance but adds offload overhead."}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)
    OUTPUT_TOOLTIPS = ("The denoised latent.",)
    FUNCTION = "sample"
    CATEGORY = "sampling"
    DESCRIPTION = "Dual KSampler for WAN 2.2 MoE: runs HIGH model for initial steps, then LOW model for remaining steps."

    def sample(self, model_high, model_low, seed, steps, switch_step, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise=1.0, offload_between_phases=False):
        total_start = time.time()
        print(f"\n[TIMING] ===== WANDualKSampler START =====")
        print(f"[TIMING] Config: steps={steps}, switch_step={switch_step}, cfg={cfg}, sampler={sampler_name}, scheduler={scheduler}")

        # Ensure switch_step is valid
        switch_step = min(switch_step, steps)

        latent = latent_image["samples"]
        latent_shape = latent.shape
        print(f"[TIMING] Latent shape: {latent_shape}")
        batch_inds = latent_image["batch_index"] if "batch_index" in latent_image else None
        noise_mask = latent_image.get("noise_mask", None)
        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

        # Phase 1: HIGH model (steps 0 to switch_step)
        print(f"[TIMING] --- Phase 1: HIGH model (steps 0-{switch_step}) ---")
        t0 = time.time()

        # Fix latent channels for HIGH model first
        latent = comfy.sample.fix_empty_latent_channels(model_high, latent)

        # Prepare noise AFTER fix_empty_latent_channels (matching KSamplerAdvanced behavior)
        noise = comfy.sample.prepare_noise(latent, seed, batch_inds)

        # Create callback that also updates hybrid step state
        base_callback_high = latent_preview.prepare_callback(model_high, steps)
        def callback_high(step, x0, x, total_steps_cb):
            set_hybrid_step(step, steps, switch_step)
            if base_callback_high:
                return base_callback_high(step, x0, x, total_steps_cb)

        # Initialize hybrid state for first step
        set_hybrid_step(0, steps, switch_step)

        samples = comfy.sample.sample(
            model_high, noise, steps, cfg, sampler_name, scheduler,
            positive, negative, latent,
            denoise=denoise,
            disable_noise=False,
            start_step=0,
            last_step=switch_step,
            force_full_denoise=False,  # Keep intermediate state for LOW model
            noise_mask=noise_mask,
            callback=callback_high,
            disable_pbar=disable_pbar,
            seed=seed
        )
        t1_high = time.time()
        high_time = t1_high - t0
        print(f"[TIMING] HIGH model ({switch_step} steps): {high_time:.2f}s ({high_time/switch_step:.2f}s/step)")

        # Record HIGH phase to database
        if TIMING_AVAILABLE and get_current_run_id():
            record_node("ksampler_HIGH", "WANDualKSampler_HIGH", t0, t1_high, {"steps": switch_step, "s_per_step": high_time/switch_step})

        # Offload HIGH model between phases if requested
        if offload_between_phases:
            t0_offload = time.time()
            comfy.model_management.unload_all_models()
            comfy.model_management.soft_empty_cache(force=True)
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            print(f"[TIMING] HIGH model offloaded: {time.time() - t0_offload:.2f}s")
        elif torch.cuda.is_available():
            # Just clear CUDA cache between phases
            torch.cuda.empty_cache()
            print(f"[TIMING] CUDA cache cleared between phases")

        # Phase 2: LOW model (steps switch_step to end)
        if switch_step < steps:
            low_steps = steps - switch_step
            print(f"[TIMING] --- Phase 2: LOW model (steps {switch_step}-{steps}) ---")
            t0 = time.time()

            # Fix latent channels for LOW model
            samples = comfy.sample.fix_empty_latent_channels(model_low, samples)

            # Create zeros for phase 2 (add_noise="disable" in KSamplerAdvanced)
            # Must be created AFTER fix_empty_latent_channels to match shape
            noise_zero = torch.zeros(samples.size(), dtype=samples.dtype, layout=samples.layout, device="cpu")

            # Create callback that also updates hybrid step state
            base_callback_low = latent_preview.prepare_callback(model_low, steps)
            def callback_low(step, x0, x, total_steps_cb):
                set_hybrid_step(step, steps, switch_step)
                if base_callback_low:
                    return base_callback_low(step, x0, x, total_steps_cb)

            samples = comfy.sample.sample(
                model_low, noise_zero, steps, cfg, sampler_name, scheduler,
                positive, negative, samples,
                denoise=denoise,
                disable_noise=True,
                start_step=switch_step,
                last_step=steps,
                force_full_denoise=True,
                noise_mask=noise_mask,
                callback=callback_low,
                disable_pbar=disable_pbar,
                seed=seed
            )
            t1_low = time.time()
            low_time = t1_low - t0
            print(f"[TIMING] LOW model ({low_steps} steps): {low_time:.2f}s ({low_time/low_steps:.2f}s/step)")

            # Record LOW phase to database
            if TIMING_AVAILABLE and get_current_run_id():
                record_node("ksampler_LOW", "WANDualKSampler_LOW", t0, t1_low, {"steps": low_steps, "s_per_step": low_time/low_steps})

        total_time = time.time() - total_start
        print(f"[TIMING] ===== WANDualKSampler TOTAL: {total_time:.2f}s =====\n")

        # Record total to database
        if TIMING_AVAILABLE and get_current_run_id():
            record_node("ksampler_TOTAL", "WANDualKSampler_TOTAL", total_start, time.time(), {"high_time": high_time, "low_time": low_time if switch_step < steps else 0})

        out = latent_image.copy()
        out["samples"] = samples
        return (out,)


class WANDualKSamplerBeta:
    """Boundary-based dual model sampler for WAN 2.2 MoE architecture.

    Uses timestep boundary (like 0.875 for T2V, 0.9 for I2V) to determine
    when to switch models, matching the MoE training configuration.
    """

    @classmethod
    def INPUT_TYPES(s):
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

    def sample(self, model_high, model_low, seed, steps, boundary, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise=1.0):
        latent = latent_image["samples"]
        batch_inds = latent_image["batch_index"] if "batch_index" in latent_image else None
        noise_mask = latent_image.get("noise_mask", None)
        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

        # Calculate sigmas and find switch point based on boundary
        sampling = model_high.get_model_object("model_sampling")
        sigmas = comfy.samplers.calculate_sigmas(sampling, scheduler, steps)

        # Convert sigmas to timesteps (0-1 range)
        timesteps = [sampling.timestep(sigma) / 1000 for sigma in sigmas.tolist()]

        # Find the step where timestep drops below boundary
        switch_step = steps
        for i, t in enumerate(timesteps[1:]):  # Skip first timestep
            if t < boundary:
                switch_step = i + 1  # +1 because we skipped first
                break

        print(f"[WANDualKSamplerBeta] Boundary={boundary}, switching at step {switch_step}/{steps}")

        # Phase 1: HIGH model (steps 0 to switch_step)
        if switch_step > 0:
            # Fix latent channels for HIGH model first
            latent = comfy.sample.fix_empty_latent_channels(model_high, latent)

            # Prepare noise AFTER fix_empty_latent_channels
            noise = comfy.sample.prepare_noise(latent, seed, batch_inds)

            callback_high = latent_preview.prepare_callback(model_high, steps)

            samples = comfy.sample.sample(
                model_high, noise, steps, cfg, sampler_name, scheduler,
                positive, negative, latent,
                denoise=denoise,
                disable_noise=False,
                start_step=0,
                last_step=switch_step,
                force_full_denoise=False,  # Keep intermediate state for LOW model
                noise_mask=noise_mask,
                callback=callback_high,
                disable_pbar=disable_pbar,
                seed=seed
            )
        else:
            samples = latent

        # Phase 2: LOW model (steps switch_step to end)
        if switch_step < steps:
            # Fix latent channels for LOW model
            samples = comfy.sample.fix_empty_latent_channels(model_low, samples)

            # Create zeros for phase 2 (add_noise="disable" in KSamplerAdvanced)
            noise_zero = torch.zeros(samples.size(), dtype=samples.dtype, layout=samples.layout, device="cpu")

            callback_low = latent_preview.prepare_callback(model_low, steps)

            samples = comfy.sample.sample(
                model_low, noise_zero, steps, cfg, sampler_name, scheduler,
                positive, negative, samples,
                denoise=denoise,
                disable_noise=True,
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
