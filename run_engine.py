# Entrypoint: run the RT2 engine — the one process that owns the model and the
# generate loop. Every control surface (run.py for biometrics, run_midi.py for
# MIDI, or any external OSC tool like SuperCollider) steers it by sending /rt2/*
# messages to the OSC control surface this opens. Launch this first, then point
# any number of sources at it.
#
# `--stub` runs the fully synthetic engine (StubOSCServer + stub model + null
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
    parser = argparse.ArgumentParser(description="Magenta RT2 engine (OSC-controlled)")
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
    parser.add_argument(
        "--record-audio",
        default=None,
        help="Record generated audio to this WAV file (48kHz stereo, 16-bit).",
    )
    return parser.parse_args(argv)


def build_engine(args: argparse.Namespace) -> RT2Engine:
    """Construct an RT2Engine with stub or real collaborators."""
    if args.stub:
        from stubs.audio_sink_stub import NullAudioSink
        from stubs.mrt2_client_stub import StubMRT2Client
        from stubs.osc_server_stub import StubOSCServer

        mrt = StubMRT2Client()
        sink = NullAudioSink()
        server = StubOSCServer()
    else:
        from src.engine.mrt2_client import MRT2Client
        from src.integrations.osc_server import OSCServer
        from src.output.audio_sink import AudioSink

        mrt = MRT2Client(size=args.size, default_prompt=args.prompt)
        sink = AudioSink()
        server = OSCServer(host=args.host, port=args.port)

    if args.record_audio:
        from src.output.recording_audio_sink import RecordingAudioSink

        sink = RecordingAudioSink(sink, args.record_audio)

    return RT2Engine(mrt, sink, server, default_prompt=args.prompt)


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
