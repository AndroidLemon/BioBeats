# MIDI -> OSC bridge: forwards MIDI input as RT2 control messages.
#
# Generalizes the same "drive RT2 from a control source" pattern as the OSC
# bridge and HR pipeline, one layer further out: a MIDI device or tool (Dubler
# 2, a keyboard, a controller, a DAW's virtual port, ...) drives RT2 by playing
# notes and twisting knobs. The bridge owns one MIDISourceProtocol + one
# OSCSenderProtocol — it is "just another OSC client" feeding the same
# /rt2/prompt and /rt2/intensity addresses OSCBridge listens on (loopback UDP),
# so nothing in the bridge has to change to support a new control surface.
#
# Unlike OSCBridge's chunk-paced latest-wins loop, every MIDI message is
# translated and forwarded individually and immediately: there is no
# audio-generation cadence to batch around here, and discrete user gestures
# (note hits, CC sweeps) shouldn't be collapsed into "whatever's freshest".

import asyncio
import logging

from src.integrations.osc_client import OSCSenderProtocol
from src.mapping.midi_to_conditioning import midi_message_to_osc
from src.midi.midi_source import MIDISourceProtocol

logger = logging.getLogger(__name__)


async def _next_message(queue: asyncio.Queue, producer: asyncio.Task):
    """Return the next queued MIDI message, or None once the producer is done
    and the queue is drained.

    Every message matters here — note_on/CC events are discrete gestures, not
    a continuously-resampled signal — so messages come back one at a time, in
    order (no latest-wins collapsing, unlike _next_latest_hr in src/pipeline.py).
    Blocks until a message is available or the producer completes.
    """
    if not queue.empty():
        return queue.get_nowait()
    if producer.done():
        return None
    get_task = asyncio.ensure_future(queue.get())
    done, _ = await asyncio.wait(
        {get_task, producer}, return_when=asyncio.FIRST_COMPLETED
    )
    if get_task in done:
        return get_task.result()
    get_task.cancel()
    if queue.empty():
        return None
    return queue.get_nowait()


class MIDIBridge:
    """Forward translated MIDI messages to an RT2 OSC bridge.

    Spawns the MIDI source, then loops: take the next message, translate it
    (midi_message_to_osc — the tunable mapping module), and send each resulting
    (address, value) pair via the OSC sender. Terminates when the source ends
    and the queue drains, stop() is called, or `max_messages` sends have gone
    out (bounding the loop for tests).
    """

    def __init__(self, source: MIDISourceProtocol, sender: OSCSenderProtocol) -> None:
        self._source = source
        self._sender = sender
        self._running = False

    def stop(self) -> None:
        """Request the forward loop to stop after the current message."""
        self._running = False

    async def run(self, max_messages: int | None = None) -> int:
        """Stream and forward MIDI-translated OSC messages. Returns the count sent."""
        queue: asyncio.Queue = asyncio.Queue()
        self._running = True
        source_task = asyncio.create_task(self._source.stream_messages(queue))
        forwarded = 0
        try:
            while self._running:
                message = await _next_message(queue, source_task)
                if message is None:
                    break
                for address, value in midi_message_to_osc(message):
                    self._sender.send(address, value)
                    forwarded += 1
                    if max_messages is not None and forwarded >= max_messages:
                        return forwarded
            return forwarded
        finally:
            self._running = False
            source_task.cancel()
            try:
                await source_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("MIDI source failed")
