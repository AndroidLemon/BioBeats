# Entrypoint: bridge a MIDI input into a running RT2 engine (run_engine.py).
#
# `--stub` runs the fully synthetic adapter (StubMIDISource + StubOSCClient, no
# hardware/network) and is the CI smoke path. Without it, the real mido/rtmidi
# input port and a loopback python-osc UDP client are wired in — point
# --osc-host/--osc-port at wherever run_engine.py is listening (defaults match).
# Real implementations are imported lazily inside the selected branch so the
# stub path never pulls mido / python-rtmidi / python-osc.
#
# Source-agnostic by design: this adapter only assumes standard MIDI messages
# (notes, velocity, CC), so any device or tool — Dubler 2, a keyboard, a
# controller, a DAW's virtual port — drives RT2 the same way. Point --port-name
# at whichever one you want to play through.
#
# --visuals-host/--visuals-port mirror every forwarded message to a second OSC
# destination via FanoutOSCSender — e.g. a hydra-osc relay so Hydra renders
# visuals in lockstep with the same control stream driving RT2. Optional and
# additive: omit them and nothing changes.

import argparse
import asyncio
import logging

from src.integrations.midi_bridge import MIDIBridge
from src.integrations.osc_server import DEFAULT_HOST, DEFAULT_PORT


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="MIDI -> OSC -> Magenta RT2 adapter")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Run with synthetic stubs (no MIDI hardware or network).",
    )
    parser.add_argument(
        "--port-name",
        default=None,
        help="MIDI input port name. Defaults to the first port mido reports.",
    )
    parser.add_argument(
        "--osc-host", default=DEFAULT_HOST, help="OSC bridge host to forward to."
    )
    parser.add_argument(
        "--osc-port", type=int, default=DEFAULT_PORT, help="OSC bridge port to forward to."
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
    parser.add_argument(
        "--record",
        default=None,
        help="Record the /rt2/* control stream to this JSONL file (replayable).",
    )
    args = parser.parse_args(argv)
    if (args.visuals_host is None) != (args.visuals_port is None):
        parser.error("--visuals-host and --visuals-port must be given together")
    return args


def build_bridge(args: argparse.Namespace) -> MIDIBridge:
    """Construct a MIDIBridge with stub or real collaborators."""
    if args.stub:
        from stubs.midi_source_stub import StubMIDISource
        from stubs.osc_client_stub import StubOSCClient

        source = StubMIDISource()
        sender = StubOSCClient()
    else:
        from src.integrations.osc_client import OSCClient
        from src.midi.midi_source import MIDISource

        source = MIDISource(port_name=args.port_name)
        sender = OSCClient(host=args.osc_host, port=args.osc_port)
        if args.visuals_host is not None:
            from src.integrations.fanout_osc_sender import FanoutOSCSender

            sender = FanoutOSCSender(
                [sender, OSCClient(host=args.visuals_host, port=args.visuals_port)]
            )

    # Record outermost so the log captures exactly what's sent (incl. to fanout).
    if args.record:
        from src.integrations.control_log import RecordingOSCSender

        sender = RecordingOSCSender(sender, args.record)

    return MIDIBridge(source, sender)


async def main_async(argv=None) -> int:
    """Build the bridge from args and run it."""
    args = parse_args(argv)
    bridge = build_bridge(args)
    # Stub run is unbounded by default; bound it so the CI smoke path terminates.
    max_messages = 1 if args.stub else None
    return await bridge.run(max_messages=max_messages)


def main(argv=None) -> int:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
