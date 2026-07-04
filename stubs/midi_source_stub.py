# Stub for src/midi/midi_source.py.
# Emits a deterministic synthetic MIDI sequence via asyncio.Queue: note_ons at
# a low/mid/high pitch, then a CC sweep across its value range. Implemented as
# a class so it matches the stateful real MIDISource interface
# (MIDISourceProtocol) exactly.

import asyncio
from types import SimpleNamespace

NOTES = (20, 70, 120)
CC_VALUES = (0, 32, 64, 96, 127)


class StubMIDISource:
    """Deterministic MIDI source for tests. No hardware, no mido/rtmidi.

    Mirrors the real MIDISource interface: a single async `stream_messages`
    coroutine that pushes MIDI-message-like objects (duck-typed: type, plus
    note/velocity or control/value) into a queue.
    """

    async def stream_messages(self, queue: asyncio.Queue, interval: float = 1.0) -> None:
        """Emit one note_on per pitch, then one control_change per CC value."""
        for note in NOTES:
            await queue.put(SimpleNamespace(type="note_on", note=note, velocity=100, channel=0))
            await asyncio.sleep(interval)
        for value in CC_VALUES:
            await queue.put(SimpleNamespace(type="control_change", control=1, value=value, channel=0))
            await asyncio.sleep(interval)
