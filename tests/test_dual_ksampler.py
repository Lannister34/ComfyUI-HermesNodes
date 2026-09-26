from types import SimpleNamespace

import comfy.model_sampling
import comfy.samplers
import pytest

from hermes_nodes.nodes.wan_dual_ksampler import wan_dual_ksampler as dual

BOUNDARY = 0.875


def wan_like_model(shift=8.0):
    sampling = comfy.model_sampling.ModelSamplingDiscreteFlow()
    sampling.set_parameters(shift=shift)
    return SimpleNamespace(get_model_object=lambda name: sampling), sampling


def first_step_starting_below(sigmas, sampling, boundary):
    for i, sigma in enumerate(sigmas[:-1]):
        if float(sampling.timestep(sigma)) / 1000 < boundary:
            return i
    return len(sigmas) - 1


@pytest.mark.parametrize("sampler_name", ["euler", "uni_pc", "dpm_2"])
@pytest.mark.parametrize("denoise", [1.0, 0.5])
def test_switch_step_scans_ksampler_sigmas_for_the_first_step_below_the_boundary(sampler_name, denoise):
    model, sampling = wan_like_model()
    run_schedule = comfy.samplers.KSampler(
        model, steps=20, device="cpu", sampler=sampler_name, scheduler="simple", denoise=denoise
    ).sigmas
    expected = first_step_starting_below(run_schedule, sampling, BOUNDARY)
    got = dual.WANDualKSamplerBeta._switch_step(model, sampler_name, "simple", 20, BOUNDARY, denoise)
    assert got == expected


def test_samplers_that_discard_the_penultimate_sigma_switch_one_step_later():
    model, _ = wan_like_model()
    assert dual.WANDualKSamplerBeta._switch_step(model, "euler", "simple", 6, 0.9, 1.0) == 3
    assert dual.WANDualKSamplerBeta._switch_step(model, "uni_pc", "simple", 6, 0.9, 1.0) == 4
    assert dual.WANDualKSamplerBeta._switch_step(model, "dpm_2", "simple", 6, 0.9, 1.0) == 4


def test_denoise_below_one_moves_the_switch_earlier():
    # KSampler.set_steps: denoise 0.5 over 20 steps runs the last 21 sigmas of a 40-step schedule
    model, _ = wan_like_model()
    assert dual.WANDualKSamplerBeta._switch_step(model, "euler", "simple", 20, BOUNDARY, 1.0) == 11
    assert dual.WANDualKSamplerBeta._switch_step(model, "euler", "simple", 20, BOUNDARY, 0.5) == 2


def test_a_run_starting_below_the_boundary_gives_the_high_model_no_steps():
    model, _ = wan_like_model()
    assert dual.WANDualKSamplerBeta._switch_step(model, "euler", "simple", 20, BOUNDARY, 0.3) == 0


def test_denoise_zero_samples_nothing_so_nothing_switches():
    model, _ = wan_like_model()
    assert dual.WANDualKSamplerBeta._switch_step(model, "euler", "simple", 20, BOUNDARY, 0.0) == 20


def test_phase_plan_covers_every_step_once_and_allows_an_empty_phase():
    assert dual._phase_plan(20, 4) == [("high", 0, 4), ("low", 4, 20)]
    assert dual._phase_plan(20, 0) == [("low", 0, 20)]
    assert dual._phase_plan(20, 20) == [("high", 0, 20)]
    assert dual._phase_plan(20, 99) == [("high", 0, 20)]
