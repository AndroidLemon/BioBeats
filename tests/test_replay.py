# Tests for replay.py: control-log replay preserves order, honors --speed timing,
# and the stub path drives a StubOSCClient end-to-end (no network).

import pytest

from replay import build_sender, main, parse_args, replay_events
from src.integrations.control_log import ControlEvent
from stubs.osc_client_stub import StubOSCClient


class _RecordingSleep:
    """Async sleep stand-in that records delays and advances a fake clock
    exactly (no overshoot), so scheduled waits equal the original gaps."""

    def __init__(self):
        self.delays = []
        self.now = 0.0

    def clock(self):
        return self.now

    async def __call__(self, seconds):
        self.delays.append(seconds)
        self.now += seconds


async def test_replay_forwards_in_order_with_scaled_gaps():
    events = [
        ControlEvent(0.0, "/rt2/prompt", "a"),
        ControlEvent(1.0, "/rt2/intensity", 0.5),
        ControlEvent(3.0, "/rt2/prompt", "b"),
    ]
    sender = StubOSCClient()
    sleep = _RecordingSleep()
    sent = await replay_events(
        events, sender, speed=2.0, sleep=sleep, clock=sleep.clock
    )

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


class _DriftingClock:
    """Fake monotonic clock: every sleep overshoots by a fixed amount, the way
    a real asyncio scheduler does."""

    def __init__(self, overshoot=0.1):
        self.now = 0.0
        self.overshoot = overshoot

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds + self.overshoot


async def test_replay_holds_absolute_schedule_under_scheduler_overshoot():
    # Per-gap sleeping accumulates overshoot: a long take ends seconds late.
    # The replay must instead target absolute timestamps, absorbing overshoot.
    events = [ControlEvent(float(t), "/rt2/intensity", 0.5) for t in range(1, 6)]
    clock = _DriftingClock(overshoot=0.1)
    sender = StubOSCClient()
    await replay_events(events, sender, sleep=clock.sleep, clock=clock)
    # Final event scheduled at t=5.0; the only unavoidable slip is the last
    # sleep's own overshoot — not five sleeps' worth accumulated.
    assert clock.now == pytest.approx(5.0 + 0.1)
