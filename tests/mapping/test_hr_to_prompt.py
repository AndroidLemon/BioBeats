# TDD tests for hr_to_prompt.py — write these first, confirm they fail,
# then implement the module until all pass.

from src.mapping.hr_to_prompt import hr_to_zone, hr_to_conditioning


def test_base_zone():
    assert hr_to_zone(110) == "base"


def test_push_zone():
    assert hr_to_zone(135) == "push"


def test_all_out_zone():
    assert hr_to_zone(160) == "all_out"


def test_boundary_goes_up():
    # At the base/push boundary (65% of 185 = 120.25), selects push
    assert hr_to_zone(121) == "push"


def test_intensity_base_is_low():
    result = hr_to_conditioning(110)
    assert 0.0 <= result["intensity"] < 0.65


def test_intensity_all_out_is_high():
    result = hr_to_conditioning(160)
    assert result["intensity"] >= 0.85


def test_intensity_is_continuous():
    # Two readings in the same zone yield different intensity values
    a = hr_to_conditioning(125)
    b = hr_to_conditioning(140)
    assert a["intensity"] != b["intensity"]


def test_pure_function():
    # Same input always returns same output
    assert hr_to_conditioning(130) == hr_to_conditioning(130)


def test_prompt_is_string():
    result = hr_to_conditioning(130)
    assert isinstance(result["prompt"], str)
    assert len(result["prompt"]) > 0


def test_custom_hr_max():
    # With lower max, 130 bpm should be all_out
    hr_to_conditioning(130, hr_max=150)
    assert hr_to_zone(130, hr_max=150) == "all_out"
