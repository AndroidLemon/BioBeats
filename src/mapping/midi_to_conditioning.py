# Maps MIDI messages to OSC control messages for the RT2 engine.
# This is the creative core of the MIDI adapter — tune it to taste. Deliberately
# source-agnostic: it only reads standard MIDI fields (type, note, velocity,
# control, value, channel), so any device or tool — Dubler 2, a keyboard, a
# controller, a DAW's virtual port — drives RT2 the same way.
#
# Now that the engine takes real note conditioning, played notes drive RT2's
# HARMONY (it generates an ensemble that follows what you play) rather than the
# old placeholder where note pitch picked a style "zone". Mapping:
#   note_on  (velocity > 0)        -> /rt2/note/on  <pitch>   (play the note)
#                                  -> /rt2/intensity <0..1>   (from velocity)
#   note_off / note_on velocity 0  -> /rt2/note/off <pitch>   (release it)
#   note on/off on the drum channel (GM channel 10) -> /rt2/drum 1 / 0
#   control_change (CC1 mod wheel, CC11 expression)
#                                  -> /rt2/intensity <0..1>   (from CC value)
#   anything else (other CCs, pitchwheel, ...) -> ignored — a sustain pedal
#     or bank-select must not slam intensity around
#
# Style/prompt is intentionally NOT driven by MIDI here — it comes from other
# sources (HR, an external OSC tool) or the engine default, so notes stay pure
# harmony. OSC message shape: list of (address, value) pairs, matching the
# address space RT2Engine exposes (src/engine/rt2_engine.py).

# General MIDI puts percussion on channel 10, which mido exposes 0-indexed as 9.
DRUM_CHANNEL = 9

# CCs that deliberately express energy; everything else is ignored.
INTENSITY_CCS = frozenset({1, 11})  # mod wheel, expression


def velocity_to_intensity(velocity: int) -> float:
    """Map MIDI velocity (0-127) to advisory intensity (0.0-1.0), continuous."""
    return round(velocity / 127, 3)


def cc_to_intensity(value: int) -> float:
    """Map a MIDI CC value (0-127) to advisory intensity (0.0-1.0), continuous."""
    return round(value / 127, 3)


def _is_note_on(msg) -> bool:
    return msg.type == "note_on" and msg.velocity > 0


def _is_note_off(msg) -> bool:
    return msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0)


def midi_message_to_osc(msg) -> list[tuple[str, object]]:
    """Translate one MIDI message into zero or more OSC (address, value) pairs.

    Pure and source-agnostic: `msg` only needs the standard mido.Message fields
    (type, channel, and note/velocity or control/value depending on type) — the
    stub source emits plain objects with the same shape.
    """
    channel = getattr(msg, "channel", 0)
    if _is_note_on(msg):
        if channel == DRUM_CHANNEL:
            return [("/rt2/drum", 1)]
        return [
            ("/rt2/note/on", msg.note),
            ("/rt2/intensity", velocity_to_intensity(msg.velocity)),
        ]
    if _is_note_off(msg):
        if channel == DRUM_CHANNEL:
            return [("/rt2/drum", 0)]
        return [("/rt2/note/off", msg.note)]
    if msg.type == "control_change" and msg.control in INTENSITY_CCS:
        return [("/rt2/intensity", cc_to_intensity(msg.value))]
    return []
