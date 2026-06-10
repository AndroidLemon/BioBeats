# Entrypoint: replay a recorded /rt2/* control log into a running engine.
#
# Reads a JSONL control log (written by RecordingOSCSender via --record) and
# re-emits each message over OSC with its original inter-event timing, so a
# recorded take drives the engine again. --speed scales playback; --stub sends to
# a StubOSCClient instead of the network (CI smoke). RT2 generation isn't
# necessarily deterministic, but the control stream is reproduced faithfully.
#
#   python run_engine.py                          # engine listening
#   python replay.py take.jsonl                   # replay the take into it
#   python replay.py take.jsonl --speed 2.0       # twice as fast

import argparse
import asyncio
import logging

from src.integrations.control_log import read_control_log
from src.integrations.osc_server import DEFAULT_HOST, DEFAULT_PORT


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Replay a /rt2/* control log over OSC")
    parser.add_argument("log", help="Path to a JSONL control log (from --record).")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Send to a stub sender instead of the network (no OSC).",
    )
    parser.add_argument("--osc-host", default=DEFAULT_HOST, help="Engine host.")
    parser.add_argument("--osc-port", type=int, default=DEFAULT_PORT, help="Engine port.")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier (2.0 = twice as fast).",
    )
    return parser.parse_args(argv)


async def replay_events(events, sender, *, speed: float = 1.0, sleep=asyncio.sleep) -> int:
    """Re-emit events over `sender`, preserving inter-event timing / `speed`.

    Waits the (scaled) gap between consecutive timestamps, then sends. `sleep` is
    injectable so tests can run instantly. Returns the number of events sent.
    """
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")
    prev_t = 0.0
    for event in events:
        gap = (event.t - prev_t) / speed
        if gap > 0:
            await sleep(gap)
        sender.send(event.address, event.value)
        prev_t = event.t
    return len(events)


def build_sender(args: argparse.Namespace):
    """Construct the OSC sender (stub or real)."""
    if args.stub:
        from stubs.osc_client_stub import StubOSCClient

        return StubOSCClient()

    from src.integrations.osc_client import OSCClient

    return OSCClient(host=args.osc_host, port=args.osc_port)


async def main_async(argv=None) -> int:
    """Read the log and replay it. Returns the number of events sent."""
    args = parse_args(argv)
    events = read_control_log(args.log)
    sender = build_sender(args)
    return await replay_events(events, sender, speed=args.speed)


def main(argv=None) -> int:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
