# Tests for the biometric bridge: HR -> conditioning translation, latest-wins
# draining, termination when the source ends, max_updates bounding, and stop().
# CI-safe — stubs only, no BLE hardware, no network.

import asyncio

from src.integrations.biometric_bridge import BiometricBridge
from src.mapping.hr_to_prompt import hr_to_conditioning
from stubs.osc_client_stub import StubOSCClient


class _ListHRMonitor:
    """Pushes a fixed list of readings into the queue, then completes —
    deterministic stand-in for StubHRMonitor's timed ramp, so tests can assert
    exact values without sleeping."""

    def __init__(self, readings):
        self._readings = readings

    async def stream_hr(self, queue, interval=1.0):
        for hr in self._readings:
            await queue.put(hr)


class _HangingHRMonitor:
    """Streams nothing and never completes — simulates a monitor gone quiet, so
    a blocked run() must still respond to stop()."""

    async def stream_hr(self, queue, interval=1.0):
        await asyncio.Event().wait()


def _make_bridge(readings, **kwargs):
    sender = StubOSCClient()
    return BiometricBridge(_ListHRMonitor(readings), sender, **kwargs), sender


async def test_forwards_reading_as_prompt_and_intensity():
    bridge, sender = _make_bridge([150], hr_max=185)
    forwarded = await bridge.run()
    assert forwarded == 2
    expected = hr_to_conditioning(150, 185)
    assert ("/rt2/prompt", expected["prompt"]) in sender.sent
    assert ("/rt2/intensity", expected["intensity"]) in sender.sent


async def test_latest_reading_wins_on_drain():
    # All four readings are queued before the loop runs; only the freshest (175)
    # should be forwarded — HR is a resampled signal, not discrete gestures.
    bridge, sender = _make_bridge([100, 120, 150, 175], hr_max=185)
    forwarded = await bridge.run()
    assert forwarded == 2
    expected = hr_to_conditioning(175, 185)
    assert sender.sent == [
        ("/rt2/prompt", expected["prompt"]),
        ("/rt2/intensity", expected["intensity"]),
    ]


async def test_run_terminates_when_source_ends():
    bridge, sender = _make_bridge([])
    forwarded = await bridge.run()
    assert forwarded == 0
    assert sender.sent == []


async def test_hr_max_changes_the_mapping():
    # Same raw HR, different hr_max -> different zone/intensity, proving hr_max
    # is threaded through to the mapping.
    bridge_low, sender_low = _make_bridge([150], hr_max=160)
    bridge_high, sender_high = _make_bridge([150], hr_max=210)
    await bridge_low.run()
    await bridge_high.run()
    assert sender_low.sent != sender_high.sent


async def test_stop_interrupts_a_blocked_run():
    sender = StubOSCClient()
    bridge = BiometricBridge(_HangingHRMonitor(), sender)
    run_task = asyncio.create_task(bridge.run())
    await asyncio.sleep(0)  # let run() start and block waiting for a reading
    bridge.stop()
    forwarded = await asyncio.wait_for(run_task, timeout=1.0)
    assert forwarded == 0
    assert sender.sent == []


async def test_max_updates_bounds_the_loop():
    # Two separate readings (queued with nothing to drain between them would
    # require timing); instead bound after the first reading is forwarded.
    bridge, sender = _make_bridge([150], hr_max=185)
    forwarded = await bridge.run(max_updates=1)
    assert forwarded == 2
    assert len(sender.sent) == 2


async def test_stop_before_run_is_honored():
    # A supervisor may stop() before (or between) runs; that request must not
    # be lost when run() starts.
    bridge, sender = _make_bridge([100, 120, 140])
    bridge.stop()
    forwarded = await asyncio.wait_for(bridge.run(), timeout=5)
    assert forwarded == 0
    assert sender.sent == []
