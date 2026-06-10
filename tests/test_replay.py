# Tests for replay.py: control-log replay preserves order, honors --speed timing,
# and the stub path drives a StubOSCClient end-to-end (no network).

import pytest

from replay import build_sender, main, parse_args, replay_events
from src.integrations.control_log import ControlEvent
from stubs.osc_client_stub import StubOSCClient


class _RecordingSleep:
    """Async sleep stand-in that records the delays it was asked to wait."""

    def __init__(self):
        self.delays = []

    async def __call__(self, seconds):
        self.delays.append(seconds)


async def test_replay_forwards_in_order_with_scaled_gaps():
    events = [
        ControlEvent(0.0, "/rt2/prompt", "a"),
        ControlEvent(1.0, "/rt2/intensity", 0.5),
        ControlEvent(3.0, "/rt2/prompt", "b"),
    ]
    sender = StubOSCClient()
    sleep = _RecordingSleep()
    sent = await replay_events(events, sender, speed=2.0, sleep=sleep)

    assert sent == 3
    assert sender.sent == [
        ("/rt2/prompt", "a"),
        ("/rt2/intensity", 0.5),
        ("/rt2/prompt", "b"),
    ]
    # Gaps 1.0 and 2.0 seconds, halved by speed=2.0. (First event has no wait.)
    assert sleep.delays == [0.5, 1.0]


async def test_replay_rejects_nonpositive_speed():
    with pytest.raises(ValueError):
        await replay_events([], StubOSCClient(), speed=0.0)


def test_parse_args_and_stub_sender():
    args = parse_args(["take.jsonl", "--stub", "--speed", "1.5"])
    assert args.log == "take.jsonl"
    assert args.stub is True
    assert args.speed == 1.5
    assert isinstance(build_sender(args), StubOSCClient)


def test_main_stub_replays_a_log_file(tmp_path):
    log = tmp_path / "take.jsonl"
    log.write_text(
        '{"t": 0.0, "address": "/rt2/prompt", "value": "ambient"}\n'
        '{"t": 0.0, "address": "/rt2/intensity", "value": 0.25}\n'
    )
    # t all 0.0 -> no real waiting; stub path -> no network.
    assert main([str(log), "--stub"]) == 2
