# Maps MIDI messages to OSC control messages for the RT2 OSC bridge.
# This is the creative core of the MIDI adapter — tune zones and prompts to taste.
# Deliberately source-agnostic: it only looks at standard MIDI message fields
# (type, note, velocity, control, value), so any MIDI device or tool — Dubler 2,
# a keyboard, a controller, a DAW's virtual port — drives RT2 the same way.
#
# Mapping (note_to_zone splits the 0-127 note range into three bands):
#   note_on (velocity > 0) -> /rt2/prompt   (zone selected by note number)
#                          -> /rt2/intensity (from velocity, continuous 0..1)
#   control_change         -> /rt2/intensity (from CC value, continuous 0..1,
#                             any CC number — agnostic to which knob is mapped)
#   anything else (note_off, pitchwheel, ...) -> ignored
#
# OSC message shape: list of (address, value) pairs, matching the address space
# OSCBridge already exposes (src/integrations/osc_bridge.py).

NOTE_MIN_DEFAULT = 0
NOTE_MAX_DEFAULT = 127

ZONE_PROMPTS = {
    "low":  "slow ambient pads, soft texture, minimal percussion, breathing space",
    "mid":  "driving rhythmic pulse, building energy, percussive momentum",
    "high": "intense percussive peak, dense rhythm, maximum energy",
}

ZONE_BOUNDARIES = [
    ("low",  0.0,  0.4),
    ("mid",  0.4,  0.75),
    ("high", 0.75, 1.0),
]


def note_to_zone(
    note: int, note_min: int = NOTE_MIN_DEFAULT, note_max: int = NOTE_MAX_DEFAULT
) -> str:
    """Return zone name from a MIDI note number. At a boundary, selects the higher zone."""
    if note_max <= note_min:
        raise ValueError(f"note_max ({note_max}) must be greater than note_min ({note_min})")
    pct = (note - note_min) / (note_max - note_min)
    zone = "low"
    for name, low, _ in ZONE_BOUNDARIES:
        if pct >= low:
            zone = name
    return zone


def zone_to_prompt(zone: str) -> str:
    """Return the style prompt for a zone name."""
    if zone not in ZONE_PROMPTS:
        raise ValueError(f"Unknown zone: {zone}")
    return ZONE_PROMPTS[zone]


def velocity_to_intensity(velocity: int) -> float:
    """Map MIDI velocity (0-127) to advisory intensity (0.0-1.0), continuous."""
    return round(velocity / 127, 3)


def cc_to_intensity(value: int) -> float:
    """Map a MIDI CC value (0-127) to advisory intensity (0.0-1.0), continuous."""
    return round(value / 127, 3)


def midi_message_to_osc(msg) -> list[tuple[str, object]]:
    """Translate one MIDI message into zero or more OSC (address, value) pairs.

    Pure and source-agnostic: `msg` only needs the standard mido.Message fields
    (type, and note/velocity or control/value depending on type) — the stub
    source emits plain objects with the same shape.
    """
    if msg.type == "note_on" and msg.velocity > 0:
        zone = note_to_zone(msg.note)
        return [
            ("/rt2/prompt", zone_to_prompt(zone)),
            ("/rt2/intensity", velocity_to_intensity(msg.velocity)),
        ]
    if msg.type == "control_change":
        return [("/rt2/intensity", cc_to_intensity(msg.value))]
    return []
