# Biometric -> OSC bridge: forwards heart rate as RT2 control messages.
#
# The project's original use case (HR -> generative music), refactored into the
# same shape as every other control surface: a BLE heart-rate monitor is "just
# another OSC client" feeding the same /rt2/prompt and /rt2/intensity addresses
# RT2Engine listens on (loopback UDP). It owns one HRMonitorProtocol + one
# OSCSenderProtocol and depends on neither the engine internals nor a concrete
# model — so it composes with MIDI and external OSC sources into one engine, and
# can fan out to visuals via FanoutOSCSender exactly like the MIDI bridge.
#
# Unlike the MIDI bridge (which forwards every discrete gesture), HR is a
# continuously-resampled signal: only the freshest reading matters at a send
# boundary, so stale readings piled up in the queue are dropped (latest-wins).
# The HR -> conditioning mapping (hr_to_conditioning) stays the tunable creative
# core; this bridge just transports its output onto the wire.

import asyncio
import logging

from src.integrations.osc_client import OSCSenderProtocol
from src.ble.hr_monitor import HRMonitorProtocol
from src.mapping.hr_to_prompt import hr_to_conditioning

logger = logging.getLogger(__name__)


async def _latest_hr(
    queue: asyncio.Queue, producer: asyncio.Task, stop_event: asyncio.Event
):
    """Return the most recent HR reading, or None once the producer is done,
    stop_event is set, and the queue is drained.

    HR is a continuously-resampled signal, so stale readings are discarded —
    only the freshest matters at a send boundary (unlike _next_message in the
    MIDI bridge, which preserves every discrete gesture in order). Blocks until
    a reading is available, the producer completes, or stop_event is set —
    racing on stop_event is what lets stop() interrupt a bridge idling on an
    empty queue (e.g. a monitor that has gone quiet).
    """
    if queue.empty():
        if producer.done() or stop_event.is_set():
            return None
        get_task = asyncio.ensure_future(queue.get())
        stop_task = asyncio.ensure_future(stop_event.wait())
        done, _ = await asyncio.wait(
            {get_task, producer, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if get_task in done:
            stop_task.cancel()
            latest = get_task.result()
        else:
            get_task.cancel()
            stop_task.cancel()
            if queue.empty():
                return None
            latest = queue.get_nowait()
    else:
        latest = queue.get_nowait()
    # Drain any readings that piled up; keep only the freshest.
    while not queue.empty():
        latest = queue.get_nowait()
    return latest


class BiometricBridge:
    """Forward HR-derived conditioning to the RT2 engine over OSC.

    Spawns the HR monitor, then loops: take the latest reading, map it
    (hr_to_conditioning — the tunable creative core), and send /rt2/prompt +
    /rt2/intensity via the OSC sender. Terminates when the monitor ends and the
    queue drains, stop() is called, or `max_updates` readings have been
    forwarded (bounding the loop for tests).
    """

    def __init__(
        self,
        source: HRMonitorProtocol,
        sender: OSCSenderProtocol,
        *,
        hr_max: int = 185,
        interval: float = 1.0,
    ) -> None:
        self._source = source
        self._sender = sender
        self._hr_max = hr_max
        self._interval = interval
        self._stop_event: asyncio.Event = asyncio.Event()

    def stop(self) -> None:
        """Request the forward loop to stop, including one blocked on the next reading."""
        self._stop_event.set()

    async def run(self, max_updates: int | None = None) -> int:
        """Stream and forward HR-translated OSC messages. Returns the count sent."""
        queue: asyncio.Queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        source_task = asyncio.create_task(
            self._source.stream_hr(queue, self._interval)
        )
        forwarded = 0
        readings = 0
        try:
            while not self._stop_event.is_set():
                hr = await _latest_hr(queue, source_task, self._stop_event)
                if hr is None:
                    break
                conditioning = hr_to_conditioning(hr, self._hr_max)
                self._sender.send("/rt2/prompt", conditioning["prompt"])
                self._sender.send("/rt2/intensity", conditioning["intensity"])
                forwarded += 2
                readings += 1
                if max_updates is not None and readings >= max_updates:
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
                logger.exception("HR source failed")
