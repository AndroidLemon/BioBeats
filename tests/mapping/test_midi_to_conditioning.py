# Tests for midi_to_conditioning.py — MIDI notes drive RT2 harmony (/rt2/note/*),
# the drum channel drives /rt2/drum, velocity/CC drive intensity.

from types import SimpleNamespace

from src.mapping.midi_to_conditioning import (
    DRUM_CHANNEL,
    cc_to_intensity,
    midi_message_to_osc,
    velocity_to_intensity,
)


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


def test_note_on_plays_the_note_and_sets_intensity():
    msg = SimpleNamespace(type="note_on", note=60, velocity=100, channel=0)
    assert midi_message_to_osc(msg) == [
        ("/rt2/note/on", 60),
        ("/rt2/intensity", velocity_to_intensity(100)),
    ]


def test_note_off_releases_the_note():
    msg = SimpleNamespace(type="note_off", note=60, velocity=64, channel=0)
    assert midi_message_to_osc(msg) == [("/rt2/note/off", 60)]


def test_note_on_with_zero_velocity_is_a_release():
    # Convention: note_on with velocity 0 is a note-off in disguise.
    msg = SimpleNamespace(type="note_on", note=60, velocity=0, channel=0)
    assert midi_message_to_osc(msg) == [("/rt2/note/off", 60)]


def test_drum_channel_note_on_plays_a_drum():
    msg = SimpleNamespace(type="note_on", note=36, velocity=100, channel=DRUM_CHANNEL)
    assert midi_message_to_osc(msg) == [("/rt2/drum", 1)]


def test_drum_channel_note_off_stops_the_drum():
    msg = SimpleNamespace(type="note_off", note=36, velocity=0, channel=DRUM_CHANNEL)
    assert midi_message_to_osc(msg) == [("/rt2/drum", 0)]


def test_control_change_maps_to_intensity():
    msg = SimpleNamespace(type="control_change", control=1, value=64, channel=0)
    assert midi_message_to_osc(msg) == [("/rt2/intensity", cc_to_intensity(64))]


def test_unknown_message_type_is_ignored():
    msg = SimpleNamespace(type="pitchwheel", pitch=0, channel=0)
    assert midi_message_to_osc(msg) == []


def test_message_without_channel_defaults_to_melodic():
    # A message lacking a `channel` attribute is treated as channel 0 (not drums).
    msg = SimpleNamespace(type="note_on", note=72, velocity=80)
    assert midi_message_to_osc(msg) == [
        ("/rt2/note/on", 72),
        ("/rt2/intensity", velocity_to_intensity(80)),
    ]


def test_pure_function():
    msg = SimpleNamespace(type="note_on", note=70, velocity=100, channel=0)
    assert midi_message_to_osc(msg) == midi_message_to_osc(msg)
