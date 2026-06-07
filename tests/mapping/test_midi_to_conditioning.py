# TDD tests for midi_to_conditioning.py — write these first, confirm they fail,
# then implement the module until all pass.

from types import SimpleNamespace

import pytest

from src.mapping.midi_to_conditioning import (
    cc_to_intensity,
    midi_message_to_osc,
    note_to_zone,
    velocity_to_intensity,
    zone_to_prompt,
)


def test_low_zone():
    assert note_to_zone(20) == "low"


def test_mid_zone():
    assert note_to_zone(70) == "mid"


def test_high_zone():
    assert note_to_zone(120) == "high"


def test_boundary_goes_up():
    # 40% of the 0-127 range is ~50.8; 51 should fall in "mid", not "low"
    assert note_to_zone(51) == "mid"


def test_zone_to_prompt_returns_nonempty_string():
    prompt = zone_to_prompt("low")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_zone_to_prompt_unknown_zone_raises():
    with pytest.raises(ValueError):
        zone_to_prompt("nonexistent")


def test_velocity_to_intensity_min():
    assert velocity_to_intensity(0) == 0.0


def test_velocity_to_intensity_max():
    assert velocity_to_intensity(127) == 1.0


def test_velocity_to_intensity_is_continuous():
    assert velocity_to_intensity(60) != velocity_to_intensity(90)


def test_cc_to_intensity_min():
    assert cc_to_intensity(0) == 0.0


def test_cc_to_intensity_max():
    assert cc_to_intensity(127) == 1.0


def test_cc_to_intensity_is_continuous():
    assert cc_to_intensity(40) != cc_to_intensity(80)


def test_note_on_maps_to_prompt_and_intensity():
    msg = SimpleNamespace(type="note_on", note=70, velocity=100, channel=0)
    result = midi_message_to_osc(msg)
    assert ("/rt2/prompt", zone_to_prompt("mid")) in result
    assert ("/rt2/intensity", velocity_to_intensity(100)) in result


def test_note_on_with_zero_velocity_is_ignored():
    # Convention: note_on with velocity 0 is a note-off in disguise.
    msg = SimpleNamespace(type="note_on", note=70, velocity=0, channel=0)
    assert midi_message_to_osc(msg) == []


def test_note_off_is_ignored():
    msg = SimpleNamespace(type="note_off", note=70, velocity=64, channel=0)
    assert midi_message_to_osc(msg) == []


def test_control_change_maps_to_intensity():
    msg = SimpleNamespace(type="control_change", control=1, value=64, channel=0)
    assert midi_message_to_osc(msg) == [("/rt2/intensity", cc_to_intensity(64))]


def test_unknown_message_type_is_ignored():
    msg = SimpleNamespace(type="pitchwheel", pitch=0, channel=0)
    assert midi_message_to_osc(msg) == []


def test_pure_function():
    # Same input always returns same output
    msg = SimpleNamespace(type="note_on", note=70, velocity=100, channel=0)
    assert midi_message_to_osc(msg) == midi_message_to_osc(msg)
