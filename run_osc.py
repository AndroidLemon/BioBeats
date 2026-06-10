# Entrypoint: run the OSC bridge so any OSC-speaking environment can steer RT2.
#
# `--stub` runs the fully synthetic bridge (StubOSCServer + stub model + null
# sink, no network/model/audio) and is the CI smoke path. Without it, the real
# python-osc UDP server, Magenta RT2 client, and sounddevice sink are wired in.
# Real implementations are imported lazily inside the selected branch so the
# stub path never pulls python-osc / magenta-rt / sounddevice.

import argparse
import asyncio
import logging

from src.engine.fsm import State
from src.engine.rt2_engine import RT2Engine
from src.integrations.osc_server import DEFAULT_HOST, DEFAULT_PORT


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="OSC -> Magenta RT2 bridge")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Run with synthetic stubs (no network, model, or audio).",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="OSC bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="OSC bind port.")
    parser.add_argument(
        "--size",
        default="mrt2_small",
        help="Magenta RT2 model size: mrt2_small (dev) or mrt2_base (demo).",
    )
    parser.add_argument(
        "--prompt",
        default="ambient",
        help="Initial style prompt before any OSC message arrives.",
    )
    return parser.parse_args(argv)


def build_engine(args: argparse.Namespace) -> RT2Engine:
    """Construct an RT2Engine with stub or real collaborators."""
    if args.stub:
        from stubs.audio_sink_stub import NullAudioSink
        from stubs.mrt2_client_stub import StubMRT2Client
        from stubs.osc_server_stub import StubOSCServer

        return RT2Engine(
            StubMRT2Client(),
            NullAudioSink(),
            StubOSCServer(),
            default_prompt=args.prompt,
        )

    from src.engine.mrt2_client import MRT2Client
    from src.integrations.osc_server import OSCServer
    from src.output.audio_sink import AudioSink

    return RT2Engine(
        MRT2Client(size=args.size, default_prompt=args.prompt),
        AudioSink(),
        OSCServer(host=args.host, port=args.port),
        default_prompt=args.prompt,
    )


async def main_async(argv=None) -> State:
    """Build the engine from args and run it."""
    args = parse_args(argv)
    engine = build_engine(args)
    # Stub run is unbounded by default; bound it so the CI smoke path terminates.
    max_chunks = 1 if args.stub else None
    return await engine.run(max_chunks=max_chunks)


def main(argv=None) -> State:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
