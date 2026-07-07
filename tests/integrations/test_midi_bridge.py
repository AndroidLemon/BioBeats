# Tests for the MIDI bridge: translation, forwarding order, termination when
# the source ends, max_messages bounding, and stop(). CI-safe — stubs only, no
# MIDI hardware, no network.

import asyncio
from types import SimpleNamespace

from src.integrations.midi_bridge import MIDIBridge
from src.mapping.midi_to_conditioning import (
    cc_to_intensity,
    velocity_to_intensity,
)
from stubs.osc_client_stub import StubOSCClient


class _ListMIDISource:
    """Pushes a fixed list of messages into the queue, then completes —
    deterministic stand-in for StubMIDISource's timed sweep, mirroring how
    StubOSCServer.dispatch() lets tests inject exact messages."""

    def __init__(self, messages):
        self._messages = messages

    async def stream_messages(self, queue, interval=1.0):
        for msg in self._messages:
            await queue.put(msg)


class _HangingMIDISource:
    """Streams nothing and never completes — simulates an idle MIDI controller
    (no notes or CC activity, port stays open) so a blocked run() must still
    respond to stop() instead of waiting on a message that may never arrive."""

    async def stream_messages(self, queue, interval=1.0):
        await asyncio.Event().wait()


def _make_bridge(messages):
    sender = StubOSCClient()
    return MIDIBridge(_ListMIDISource(messages), sender), sender


async def test_forwards_note_on_as_note_and_intensity():
    msg = SimpleNamespace(type="note_on", note=70, velocity=100, channel=0)
    bridge, sender = _make_bridge([msg])
    forwarded = await bridge.run()
    assert forwarded == 2
    assert ("/rt2/note/on", 70) in sender.sent
    assert ("/rt2/intensity", velocity_to_intensity(100)) in sender.sent


async def test_forwards_control_change_as_intensity():
    msg = SimpleNamespace(type="control_change", control=1, value=64, channel=0)
    bridge, sender = _make_bridge([msg])
    forwarded = await bridge.run()
    assert forwarded == 1
    assert sender.sent == [("/rt2/intensity", cc_to_intensity(64))]


async def test_ignores_unmapped_messages():
    pitchwheel = SimpleNamespace(type="pitchwheel", pitch=0, channel=0)
    bridge, sender = _make_bridge([pitchwheel])
    forwarded = await bridge.run()
    assert forwarded == 0
    assert sender.sent == []


async def test_forwards_messages_in_order():
    messages = [
        SimpleNamespace(type="note_on", note=20, velocity=80, channel=0),
        SimpleNamespace(type="control_change", control=1, value=32, channel=0),
        SimpleNamespace(type="note_off", note=20, velocity=0, channel=0),
    ]
    bridge, sender = _make_bridge(messages)
    forwarded = await bridge.run()
    assert forwarded == 4  # 2 (note/on+intensity) + 1 (intensity) + 1 (note/off)
    addresses = [addr for addr, _ in sender.sent]
    assert addresses == [
        "/rt2/note/on", "/rt2/intensity",
        "/rt2/intensity",
        "/rt2/note/off",
    ]


async def test_run_terminates_when_source_ends():
    bridge, sender = _make_bridge([])
    forwarded = await bridge.run()
    assert forwarded == 0
    assert sender.sent == []


async def test_stop_interrupts_a_blocked_run():
    sender = StubOSCClient()
    bridge = MIDIBridge(_HangingMIDISource(), sender)
    run_task = asyncio.create_task(bridge.run())
    await asyncio.sleep(0)  # let run() start and block waiting for a message
    bridge.stop()
    forwarded = await asyncio.wait_for(run_task, timeout=1.0)
    assert forwarded == 0
    assert sender.sent == []


async def test_max_messages_bounds_the_loop():
    messages = [
        SimpleNamespace(type="note_on", note=20, velocity=80, channel=0),
        SimpleNamespace(type="note_on", note=120, velocity=110, channel=0),
    ]
    bridge, sender = _make_bridge(messages)
    forwarded = await bridge.run(max_messages=1)
    assert forwarded == 1
    assert len(sender.sent) == 1


async def test_stop_before_run_is_honored():
    # A supervisor may stop() before (or between) runs; that request must not
    # be lost when run() starts.
    bridge, sender = _make_bridge(
        [SimpleNamespace(type="note_on", note=60, velocity=100, channel=0)]
    )
    bridge.stop()
    forwarded = await asyncio.wait_for(bridge.run(), timeout=5)
    assert forwarded == 0
    assert sender.sent == []


class _ExplodingMIDISource:
    """Yields one message, then dies — an unplugged controller."""

    async def stream_messages(self, queue, interval=1.0):
        await queue.put(
            SimpleNamespace(type="note_on", note=60, velocity=100, channel=0)
        )
        raise OSError("MIDI port gone")


async def test_source_failure_terminates_run_and_is_logged(caplog):
    sender = StubOSCClient()
    bridge = MIDIBridge(_ExplodingMIDISource(), sender)
    forwarded = await asyncio.wait_for(bridge.run(), timeout=5)
    assert forwarded == 2  # note/on + intensity from the message before death
    assert "MIDI source failed" in caplog.text
