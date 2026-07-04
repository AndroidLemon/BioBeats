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


def hr_to_zone(hr: int, hr_max: int = HR_MAX_DEFAULT) -> str:
    """Return zone name from raw HR int. At a boundary, selects the higher zone."""
    pct = hr / hr_max
    zone = "base"
    for name, low, _ in ZONE_BOUNDARIES:
        if pct >= low:
            zone = name
    return zone


def zone_to_conditioning(zone: str, hr: int, hr_max: int = HR_MAX_DEFAULT) -> dict:
    """Return MRT2 conditioning dict with continuously interpolated intensity."""
    for name, low, high in ZONE_BOUNDARIES:
        if name == zone:
            pct = hr / hr_max
            # Normalize position within zone to 0.0–1.0, then scale to global range
            zone_progress = (pct - low) / (high - low) if high > low else 1.0
            zone_progress = max(0.0, min(1.0, zone_progress))
            intensity = low + zone_progress * (high - low)
            return {"prompt": ZONE_PROMPTS[zone], "intensity": round(intensity, 3)}
    raise ValueError(f"Unknown zone: {zone}")


def hr_to_conditioning(hr: int, hr_max: int = HR_MAX_DEFAULT) -> dict:
    """Top-level pure function: HR int → MRT2 conditioning dict.
    Composes hr_to_zone and zone_to_conditioning.
    No global state. Same input always returns same output.
    """
    zone = hr_to_zone(hr, hr_max)
    return zone_to_conditioning(zone, hr, hr_max)
