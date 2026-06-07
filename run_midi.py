# Entrypoint: bridge a MIDI input into a running OSC bridge (run_osc.py).
#
# `--stub` runs the fully synthetic adapter (StubMIDISource + StubOSCClient, no
# hardware/network) and is the CI smoke path. Without it, the real mido/rtmidi
# input port and a loopback python-osc UDP client are wired in — point
# --osc-host/--osc-port at wherever run_osc.py is listening (defaults match).
# Real implementations are imported lazily inside the selected branch so the
# stub path never pulls mido / python-rtmidi / python-osc.
#
# Source-agnostic by design: this adapter only assumes standard MIDI messages
# (notes, velocity, CC), so any device or tool — Dubler 2, a keyboard, a
# controller, a DAW's virtual port — drives RT2 the same way. Point --port-name
# at whichever one you want to play through.

import argparse
import asyncio
import logging

from src.integrations.midi_bridge import MIDIBridge
from src.integrations.osc_bridge import DEFAULT_HOST, DEFAULT_PORT


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
    return parser.parse_args(argv)


def build_bridge(args: argparse.Namespace) -> MIDIBridge:
    """Construct a MIDIBridge with stub or real collaborators."""
    if args.stub:
        from stubs.midi_source_stub import StubMIDISource
        from stubs.osc_client_stub import StubOSCClient

        return MIDIBridge(StubMIDISource(), StubOSCClient())

    from src.integrations.osc_client import OSCClient
    from src.midi.midi_source import MIDISource

    return MIDIBridge(
        MIDISource(port_name=args.port_name),
        OSCClient(host=args.osc_host, port=args.osc_port),
    )


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
