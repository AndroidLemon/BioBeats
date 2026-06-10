# Entrypoint: bridge a BLE heart-rate monitor into a running RT2 engine
# (run_engine.py) over OSC. This is the project's flagship source — HR drives the
# music — but it's now "just another OSC client", a peer of run_midi.py.
#
# `--stub` runs the fully synthetic adapter (StubHRMonitor + StubOSCClient, no
# hardware/network) and is the CI smoke path. Without it, the real bleak BLE
# monitor and a loopback python-osc UDP client are wired in — point
# --osc-host/--osc-port at wherever run_engine.py is listening (defaults match).
# Real implementations are imported lazily inside the selected branch so the stub
# path never pulls bleak / python-osc.
#
# --visuals-host/--visuals-port mirror every forwarded message to a second OSC
# destination via FanoutOSCSender — e.g. a hydra-osc relay so Hydra renders
# visuals in lockstep with the same control stream driving RT2. Optional and
# additive: omit them and nothing changes.

import argparse
import asyncio
import logging

from src.integrations.biometric_bridge import BiometricBridge
from src.integrations.osc_server import DEFAULT_HOST, DEFAULT_PORT


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Biometric (HR) -> OSC -> RT2 adapter")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Run with synthetic stubs (no BLE hardware or network).",
    )
    parser.add_argument(
        "--hr-max",
        type=int,
        default=185,
        help="Max heart rate used for zone mapping.",
    )
    parser.add_argument(
        "--osc-host", default=DEFAULT_HOST, help="RT2 engine host to forward to."
    )
    parser.add_argument(
        "--osc-port", type=int, default=DEFAULT_PORT, help="RT2 engine port to forward to."
    )
    parser.add_argument(
        "--visuals-host",
        default=None,
        help=(
            "Optional second OSC destination host to mirror every forwarded "
            "message to — e.g. a hydra-osc relay driving Hydra visuals in "
            "lockstep with RT2. Requires --visuals-port."
        ),
    )
    parser.add_argument(
        "--visuals-port",
        type=int,
        default=None,
        help="Optional second OSC destination port. Requires --visuals-host.",
    )
    args = parser.parse_args(argv)
    if (args.visuals_host is None) != (args.visuals_port is None):
        parser.error("--visuals-host and --visuals-port must be given together")
    return args


def build_bridge(args: argparse.Namespace) -> BiometricBridge:
    """Construct a BiometricBridge with stub or real collaborators."""
    if args.stub:
        from stubs.hr_monitor_stub import StubHRMonitor
        from stubs.osc_client_stub import StubOSCClient

        # interval=0 so the stub ramp doesn't sleep between readings.
        return BiometricBridge(
            StubHRMonitor(), StubOSCClient(), hr_max=args.hr_max, interval=0
        )

    from src.ble.hr_monitor import HRMonitor
    from src.integrations.osc_client import OSCClient

    sender = OSCClient(host=args.osc_host, port=args.osc_port)
    if args.visuals_host is not None:
        from src.integrations.fanout_osc_sender import FanoutOSCSender

        sender = FanoutOSCSender(
            [sender, OSCClient(host=args.visuals_host, port=args.visuals_port)]
        )

    return BiometricBridge(HRMonitor(), sender, hr_max=args.hr_max)


async def main_async(argv=None) -> int:
    """Build the bridge from args and run it."""
    args = parse_args(argv)
    bridge = build_bridge(args)
    # Stub run is unbounded by default; bound it so the CI smoke path terminates.
    max_updates = 1 if args.stub else None
    return await bridge.run(max_updates=max_updates)


def main(argv=None) -> int:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
