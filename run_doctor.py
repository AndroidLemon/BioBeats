# Entrypoint: preflight diagnostics for the real BioBeats rig.
#
# Runs each layer's check independently and prints a report so you can tell which
# part of the real path (Apple-Silicon/MLX, OSC port, audio device, BLE/OTBeat,
# RT2 model) is or isn't working — before fighting with `python run_engine.py`.
# Exits non-zero if any check FAILs (WARN/SKIP do not fail), so it doubles as a
# CI/setup gate.
#
#   python run_doctor.py                      # all checks, fast (no model load)
#   python run_doctor.py --only osc-port,audio
#   python run_doctor.py --skip ble
#   python run_doctor.py --play-tone          # actually play a test tone
#   python run_doctor.py --load-model         # actually construct RT2 + generate

import argparse
import sys

from src.diagnostics.doctor import (
    CHECK_ORDER,
    CheckStatus,
    Doctor,
    DoctorConfig,
    format_report,
    summarize,
)


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="BioBeats rig preflight diagnostics")
    parser.add_argument(
        "--only",
        default=None,
        help=f"Comma-separated checks to run (of: {', '.join(CHECK_ORDER)}).",
    )
    parser.add_argument(
        "--skip",
        default=None,
        help="Comma-separated checks to skip.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="OSC host to check.")
    parser.add_argument("--port", type=int, default=5005, help="OSC port to check.")
    parser.add_argument(
        "--name-prefix", default="OTbeat", help="BLE name prefix to look for."
    )
    parser.add_argument(
        "--scan-seconds", type=float, default=5.0, help="BLE scan duration."
    )
    parser.add_argument(
        "--size", default="mrt2_small", help="RT2 model size to check/load."
    )
    parser.add_argument(
        "--load-model",
        action="store_true",
        help="Actually construct RT2 and generate one chunk (slow, Apple Silicon).",
    )
    parser.add_argument(
        "--play-tone",
        action="store_true",
        help="Actually open the audio device and play a short test tone.",
    )
    return parser.parse_args(argv)


def selected_names(only: str | None, skip: str | None) -> list[str] | None:
    """Resolve --only/--skip into a list of check names (or None for all)."""
    names = CHECK_ORDER if only is None else [n.strip() for n in only.split(",")]
    if skip:
        skipped = {n.strip() for n in skip.split(",")}
        names = [n for n in names if n not in skipped]
    return names


def main(argv=None) -> int:
    """Run the diagnostics and return a process exit code (0 = no failures)."""
    args = parse_args(argv)
    config = DoctorConfig(
        osc_host=args.host,
        osc_port=args.port,
        ble_name_prefix=args.name_prefix,
        scan_seconds=args.scan_seconds,
        model_size=args.size,
        load_model=args.load_model,
        play_tone=args.play_tone,
    )
    results = Doctor(config).run(selected_names(args.only, args.skip))
    print(format_report(results))
    return 1 if summarize(results) is CheckStatus.FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
