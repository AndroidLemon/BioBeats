# Maps a raw heart rate integer to a Magenta RT2 conditioning dictionary.
# This is the creative core of the HR adapter — tune prompts to taste.
#
# OTF zone model (% of max HR, default max=185):
#   Base:     <65%  → <120 bpm  — recovery, low effort
#   Push:    65–84% → 120–155   — building, sustained effort
#   All Out:  85%+  → 156+      — peak intensity
#
# Intensity is continuous (0.0–1.0), interpolated within each zone.
# Conditioning dict shape: {"prompt": str, "intensity": float}

HR_MAX_DEFAULT = 185

ZONE_PROMPTS = {
    "base":    "slow ambient pads, soft texture, minimal percussion, breathing space",
    "push":    "driving rhythmic pulse, building energy, percussive momentum",
    "all_out": "intense percussive peak, dense rhythm, maximum energy",
}

ZONE_BOUNDARIES = [
    ("base",    0.0,  0.65),
    ("push",    0.65, 0.85),
    ("all_out", 0.85, 1.0),
]

# Hysteresis: a zone change must clear the boundary by this fraction of max HR
# (~4 bpm at the default max). Without it, HR oscillating around a boundary
# flaps the prompt every reading — and every flap costs a style re-embed.
ZONE_MARGIN = 0.02


def hr_to_zone(
    hr: int,
    hr_max: int = HR_MAX_DEFAULT,
    previous: str | None = None,
    margin: float = ZONE_MARGIN,
) -> str:
    """Return zone name from raw HR int. At a boundary, selects the higher zone.

    With `previous` given, boundary crossings are sticky: leaving the previous
    zone requires clearing the boundary by `margin` in the direction of travel,
    so readings that straddle a boundary keep the current zone. Pure — the
    caller (e.g. the biometric bridge) threads the previous zone through.
    """
    pct = hr / hr_max
    raw = "base"
    for name, low, _ in ZONE_BOUNDARIES:
        if pct >= low:
            raw = name
    names = [name for name, _, _ in ZONE_BOUNDARIES]
    lows = {name: low for name, low, _ in ZONE_BOUNDARIES}
    if previous not in lows or raw == previous:
        return raw
    if names.index(raw) > names.index(previous):
        # Moving up: each crossed boundary must be cleared by the margin.
        idx = names.index(raw)
        while idx > names.index(previous) and pct < lows[names[idx]] + margin:
            idx -= 1
        return names[idx]
    # Moving down: stay put until pct drops `margin` below the previous floor.
    if pct >= lows[previous] - margin:
        return previous
    return raw


def zone_to_conditioning(zone: str, hr: int, hr_max: int = HR_MAX_DEFAULT) -> dict:
    """Return MRT2 conditioning dict with continuously interpolated intensity."""
    for name, low, high in ZONE_BOUNDARIES:
        if name == zone:
            pct = hr / hr_max
            # Normalize position within zone to 0.0–1.0, then scale to global range
            zone_progress = (pct - low) / (high - low) if high > low else 1.0
            zone_progress = max(0.0, min(1.0, zone_progress))
            intensity = low + zone_progress * (high - low)
            return {
                "prompt": ZONE_PROMPTS[zone],
                "intensity": round(intensity, 3),
                "zone": zone,
            }
    raise ValueError(f"Unknown zone: {zone}")


def hr_to_conditioning(
    hr: int, hr_max: int = HR_MAX_DEFAULT, previous_zone: str | None = None
) -> dict:
    """Top-level pure function: HR int → MRT2 conditioning dict.

    Composes hr_to_zone (sticky around boundaries when `previous_zone` is
    given) and zone_to_conditioning. The returned dict carries the selected
    "zone" so callers can thread it back in as `previous_zone`. No global
    state — the same inputs always return the same output.
    """
    zone = hr_to_zone(hr, hr_max, previous=previous_zone)
    return zone_to_conditioning(zone, hr, hr_max)
