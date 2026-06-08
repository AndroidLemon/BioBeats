# Tests for the MIDI source stub. Proves the class interface and the
# deterministic note/CC sweep contract.

import asyncio

from stubs.midi_source_stub import CC_VALUES, NOTES, StubMIDISource


async def test_stream_messages_emits_note_then_cc_sweep():
    queue: asyncio.Queue = asyncio.Queue()
    # interval=0 so the test does not actually sleep
    await StubMIDISource().stream_messages(queue, interval=0)
    messages = [queue.get_nowait() for _ in range(queue.qsize())]

    notes = [m for m in messages if m.type == "note_on"]
    ccs = [m for m in messages if m.type == "control_change"]
    assert [m.note for m in notes] == list(NOTES)
    assert [m.value for m in ccs] == list(CC_VALUES)
    assert messages == notes + ccs


async def test_note_on_messages_have_nonzero_velocity():
    queue: asyncio.Queue = asyncio.Queue()
    await StubMIDISource().stream_messages(queue, interval=0)
    messages = [queue.get_nowait() for _ in range(queue.qsize())]
    assert all(m.velocity > 0 for m in messages if m.type == "note_on")
