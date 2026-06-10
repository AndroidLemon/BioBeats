# MIDI -> OSC bridge: forwards MIDI input as RT2 control messages.
#
# Generalizes the same "drive RT2 from a control source" pattern as the engine
# and biometric bridge, one layer further out: a MIDI device or tool (Dubler
# 2, a keyboard, a controller, a DAW's virtual port, ...) drives RT2 by playing
# notes and twisting knobs. The bridge owns one MIDISourceProtocol + one
# OSCSenderProtocol — it is "just another OSC client" feeding the same
# /rt2/prompt and /rt2/intensity addresses RT2Engine listens on (loopback UDP),
# so nothing in the bridge has to change to support a new control surface.
#
# Unlike RT2Engine's chunk-paced latest-wins loop, every MIDI message is
# translated and forwarded individually and immediately: there is no
# audio-generation cadence to batch around here, and discrete user gestures
# (note hits, CC sweeps) shouldn't be collapsed into "whatever's freshest".

import asyncio
import logging

from src.integrations.osc_client import OSCSenderProtocol
from src.mapping.midi_to_conditioning import midi_message_to_osc
from src.midi.midi_source import MIDISourceProtocol

logger = logging.getLogger(__name__)


async def _next_message(queue: asyncio.Queue, producer: asyncio.Task, stop_event: asyncio.Event):
    """Return the next queued MIDI message, or None once the producer is done,
    stop_event is set, and the queue is drained.

    Every message matters here — note_on/CC events are discrete gestures, not
    a continuously-resampled signal — so messages come back one at a time, in
    order (no latest-wins collapsing, unlike _next_latest_hr in src/pipeline.py).
    Blocks until a message is available, the producer completes, or stop_event
    is set — racing on stop_event is what lets stop() interrupt a bridge that's
    idling on an empty queue (e.g. a MIDI controller with no current activity).
    """
    if not queue.empty():
        return queue.get_nowait()
    if producer.done() or stop_event.is_set():
        return None
    get_task = asyncio.ensure_future(queue.get())
    stop_task = asyncio.ensure_future(stop_event.wait())
    done, _ = await asyncio.wait(
        {get_task, producer, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if get_task in done:
        stop_task.cancel()
        return get_task.result()
    get_task.cancel()
    stop_task.cancel()
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
        self._stop_event: asyncio.Event = asyncio.Event()

    def stop(self) -> None:
        """Request the forward loop to stop, including one blocked on the next message."""
        self._stop_event.set()

    async def run(self, max_messages: int | None = None) -> int:
        """Stream and forward MIDI-translated OSC messages. Returns the count sent."""
        queue: asyncio.Queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        source_task = asyncio.create_task(self._source.stream_messages(queue))
        forwarded = 0
        try:
            while not self._stop_event.is_set():
                message = await _next_message(queue, source_task, self._stop_event)
                if message is None:
                    break
                for address, value in midi_message_to_osc(message):
                    self._sender.send(address, value)
                    forwarded += 1
                    if max_messages is not None and forwarded >= max_messages:
                        return forwarded
            return forwarded
        finally:
            self._stop_event.set()
            source_task.cancel()
            try:
                await source_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("MIDI source failed")
