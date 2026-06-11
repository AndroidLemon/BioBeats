# Preflight diagnostics — "does the real path actually work on this machine?"
#
# Everything in BioBeats has a stub path that runs clean on CI, but the real
# rig (Apple-Silicon Mac + OTBeat Burn over BLE + RT2/MLX + an audio device) has
# never been exercised here. This module checks each layer INDEPENDENTLY so that
# when something doesn't work, you know exactly which layer failed and what to do
# about it — rather than staring at one opaque failure from `python run_engine.py`.
#
# Design mirrors the rest of the project: the pure parts (status aggregation,
# report formatting, check selection) are unit-tested with no hardware, and each
# hardware check lazy-imports its heavy dependency and NEVER raises — a broken
# layer returns a FAIL/SKIP result so the other checks still run. Run it via
# run_doctor.py.

import enum
import socket
from dataclasses import dataclass, field
from typing import Callable


class CheckStatus(enum.Enum):
    """Outcome of a single diagnostic check."""

    PASS = "pass"
    WARN = "warn"  # works, but notable (e.g. not Apple Silicon, no OTBeat seen)
    FAIL = "fail"  # a required capability is broken (e.g. OSC port in use)
    SKIP = "skip"  # couldn't check (dependency missing / not applicable)


# Glyphs for the rendered report.
_GLYPH = {
    CheckStatus.PASS: "✓",
    CheckStatus.WARN: "!",
    CheckStatus.FAIL: "✗",
    CheckStatus.SKIP: "–",
}


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one check: what it is, how it went, and what to do next."""

    name: str
    status: CheckStatus
    detail: str = ""
    hint: str | None = None  # actionable next step, shown only when not PASS


@dataclass(frozen=True)
class DoctorConfig:
    """Inputs the checks need. Defaults match the engine/adapters' defaults."""

    osc_host: str = "127.0.0.1"
    osc_port: int = 5005
    ble_name_prefix: str = "OTbeat"
    scan_seconds: float = 5.0
    model_size: str = "mrt2_small"
    load_model: bool = False  # actually construct RT2 + generate (slow); opt-in
    play_tone: bool = False  # actually open the audio device + play a tone; opt-in


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — exhaustively unit-testable.
# ---------------------------------------------------------------------------


def summarize(results: list[CheckResult]) -> CheckStatus:
    """Roll a list of results into one overall status.

    FAIL if anything failed, else WARN if anything warned, else PASS. SKIPs are
    informational and never change the overall verdict.
    """
    statuses = {r.status for r in results}
    if CheckStatus.FAIL in statuses:
        return CheckStatus.FAIL
    if CheckStatus.WARN in statuses:
        return CheckStatus.WARN
    return CheckStatus.PASS


def select_checks(all_names: list[str], names: list[str] | None) -> list[str]:
    """Return the checks to run, in canonical order.

    `names` None -> all. Otherwise keep only known names, preserving the
    canonical order in `all_names` (so output ordering is stable regardless of
    how the user listed them). Unknown names are dropped.
    """
    if names is None:
        return list(all_names)
    requested = set(names)
    return [name for name in all_names if name in requested]


def format_report(results: list[CheckResult]) -> str:
    """Render results as an aligned, human-readable report with hints."""
    if not results:
        return "no checks run"
    width = max(len(r.name) for r in results)
    lines = []
    for r in results:
        line = f"{_GLYPH[r.status]} {r.name.ljust(width)}  {r.detail}".rstrip()
        lines.append(line)
        if r.hint and r.status is not CheckStatus.PASS:
            lines.append(f"  {' ' * width}  → {r.hint}")
    overall = summarize(results)
    lines.append("")
    lines.append(f"{_GLYPH[overall]} overall: {overall.value.upper()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks. Each lazy-imports its dependency and never raises.
# ---------------------------------------------------------------------------


def check_env(config: DoctorConfig) -> CheckResult:
    """Python version + interpreter sanity."""
    import sys

    v = sys.version_info
    detail = f"Python {v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < (3, 12):
        return CheckResult(
            "env", CheckStatus.FAIL, detail, hint="BioBeats requires Python >= 3.12"
        )
    return CheckResult("env", CheckStatus.PASS, detail)


def _is_engine_host() -> bool:
    """True if this machine can run the RT2 engine (Apple-Silicon Mac / MLX).

    Off-target hosts run only the control-surface adapters, so engine-only
    capabilities (audio output, RT2/MLX) are informational there, not failures.
    """
    import platform

    return platform.system() == "Darwin" and platform.machine() == "arm64"


def check_apple_silicon(config: DoctorConfig) -> CheckResult:
    """RT2 runs on MLX, which is Apple-Silicon only. Warn (not fail) elsewhere —
    the OSC/MIDI/biometric adapters still work off-Mac; only the engine needs it.
    """
    import platform

    detail = f"{platform.system()} {platform.machine()}"
    if _is_engine_host():
        return CheckResult("apple-silicon", CheckStatus.PASS, detail)
    return CheckResult(
        "apple-silicon",
        CheckStatus.WARN,
        detail,
        hint=(
            "RT2/MLX needs an Apple-Silicon Mac to run the engine; control-surface"
            " adapters (OSC/MIDI/HR) still work here, pointed at an engine elsewhere"
        ),
    )


def check_osc_port(config: DoctorConfig) -> CheckResult:
    """Can the engine bind its OSC control port? 'Address already in use' is the
    single most common real startup failure, so check it directly with a UDP
    bind (no python-osc needed)."""
    name = "osc-port"
    detail = f"{config.osc_host}:{config.osc_port}"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((config.osc_host, config.osc_port))
    except OSError as exc:
        return CheckResult(
            name,
            CheckStatus.FAIL,
            f"{detail} — {exc.strerror or exc}",
            hint="another process holds the port; stop it or pass --port a free one",
        )
    finally:
        sock.close()
    return CheckResult(name, CheckStatus.PASS, f"{detail} bindable")


def check_audio(config: DoctorConfig) -> CheckResult:
    """Is there an output device sounddevice/PortAudio can use? Optionally play a
    short test tone (config.play_tone)."""
    name = "audio"
    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001 - import/PortAudio failure is the signal
        # On the engine's target rig, run_engine.py wires in a real AudioSink, so
        # missing PortAudio is a genuine FAIL. On other hosts the engine isn't
        # applicable (only adapters run), so it's just informational (SKIP).
        status = CheckStatus.FAIL if _is_engine_host() else CheckStatus.SKIP
        return CheckResult(
            name,
            status,
            f"sounddevice unavailable: {exc}",
            hint="install PortAudio (`brew install portaudio`) and `uv sync`",
        )
    try:
        default_out = sd.query_devices(kind="output")
    except Exception as exc:  # noqa: BLE001 - no device / no host API
        return CheckResult(
            name,
            CheckStatus.FAIL,
            f"no output device: {exc}",
            hint="connect/select an output device in system audio settings",
        )
    device_name = default_out.get("name", "?")
    if config.play_tone:
        try:
            _play_test_tone(sd)
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name,
                CheckStatus.FAIL,
                f"output device '{device_name}' could not play: {exc}",
            )
    return CheckResult(name, CheckStatus.PASS, f"output: {device_name}")


def _play_test_tone(sd, seconds: float = 0.4, freq: float = 440.0) -> None:
    """Play a short sine on the default output (only when --play-tone is set)."""
    import numpy as np

    sample_rate = 48000
    t = np.linspace(0.0, seconds, int(sample_rate * seconds), endpoint=False)
    tone = (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    stereo = np.column_stack([tone, tone])
    sd.play(stereo, samplerate=sample_rate)
    sd.wait()


def check_ble(config: DoctorConfig) -> CheckResult:
    """Can we scan BLE, and is an OTBeat in range? bleak's scan is async, so run
    it on a private loop with a timeout."""
    name = "ble"
    try:
        import asyncio

        from bleak import BleakScanner
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name, CheckStatus.SKIP, f"bleak unavailable: {exc}", hint="`uv sync`"
        )

    async def _scan() -> list:
        return await BleakScanner.discover(timeout=config.scan_seconds)

    try:
        devices = asyncio.run(_scan())
    except Exception as exc:  # noqa: BLE001 - no adapter / permissions
        return CheckResult(
            name,
            CheckStatus.FAIL,
            f"scan failed: {exc}",
            hint="enable Bluetooth and grant the terminal Bluetooth permission",
        )
    prefix = config.ble_name_prefix.lower()
    matches = [d for d in devices if (d.name or "").lower().startswith(prefix)]
    if matches:
        return CheckResult(
            name, CheckStatus.PASS, f"found {matches[0].name} ({matches[0].address})"
        )
    return CheckResult(
        name,
        CheckStatus.WARN,
        f"BLE works ({len(devices)} devices) but no '{config.ble_name_prefix}*' seen",
        hint="wake the OTBeat Burn and disconnect it from the OTF app so it can pair",
    )


def check_rt2_model(config: DoctorConfig) -> CheckResult:
    """Is the RT2/MLX stack importable, are weights present, and (opt-in) can it
    actually generate a chunk? STRICTLY RT2 — uses the MLX backend only."""
    name = "rt2-model"
    try:
        from magenta_rt import paths
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name, CheckStatus.SKIP, f"magenta-rt unavailable: {exc}", hint="`uv sync`"
        )

    model_dir = paths.models_dir() / config.model_size
    weights_present = model_dir.exists()

    if not config.load_model:
        if weights_present:
            return CheckResult(
                name, CheckStatus.PASS, f"weights present: {model_dir}"
            )
        return CheckResult(
            name,
            CheckStatus.WARN,
            f"weights not found at {model_dir}",
            hint="run once with --load-model to download, or pre-fetch the model",
        )

    # Opt-in heavy path: actually construct the MLX system and generate a chunk.
    try:
        import time

        from src.engine.mrt2_client import CHUNK_FRAMES
        from magenta_rt.mlx.system import MagentaRT2SystemMlxfn

        mrt = MagentaRT2SystemMlxfn(size=config.model_size)
        style = mrt.embed_style("ambient")
        # Exclude construction/embedding and a cold-start chunk from the timing:
        # the real-time budget is about STEADY-STATE generation, so warm up once
        # (discarded) and time a second, state-threaded chunk.
        _, state = mrt.generate(style=style, frames=CHUNK_FRAMES, state=None)
        start = time.monotonic()
        mrt.generate(style=style, frames=CHUNK_FRAMES, state=state)
        elapsed = time.monotonic() - start
    except Exception as exc:  # noqa: BLE001 - import/build/generate failure
        return CheckResult(
            name,
            CheckStatus.FAIL,
            f"generation failed: {exc}",
            hint="RT2 requires an Apple-Silicon Mac (MLX); check the model download",
        )
    # CHUNK_FRAMES is 2s of audio: a steady-state chunk over ~2s can't keep up.
    budget = "real-time OK" if elapsed < 2.0 else "SLOWER THAN REAL TIME"
    return CheckResult(
        name, CheckStatus.PASS, f"steady-state chunk in {elapsed:.1f}s ({budget})"
    )


# Canonical order: cheapest/most-fundamental first, heaviest (model) last.
_RUNNERS: dict[str, Callable[[DoctorConfig], CheckResult]] = {
    "env": check_env,
    "apple-silicon": check_apple_silicon,
    "osc-port": check_osc_port,
    "audio": check_audio,
    "ble": check_ble,
    "rt2-model": check_rt2_model,
}
CHECK_ORDER: list[str] = list(_RUNNERS)


@dataclass
class Doctor:
    """Runs the selected checks and collects their results."""

    config: DoctorConfig = field(default_factory=DoctorConfig)

    def run(self, names: list[str] | None = None) -> list[CheckResult]:
        """Run the selected checks (default: all), in canonical order."""
        selected = select_checks(CHECK_ORDER, names)
        results = []
        for check_name in selected:
            runner = _RUNNERS[check_name]
            try:
                results.append(runner(self.config))
            except Exception as exc:  # noqa: BLE001 - a check must never abort the run
                results.append(
                    CheckResult(check_name, CheckStatus.FAIL, f"check crashed: {exc!r}")
                )
        return results
