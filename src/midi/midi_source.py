# MIDI input source.
#
# Defines MIDISourceProtocol, the interface shared by the real mido-backed
# source (lazy-imports mido/python-rtmidi) and StubMIDISource. The MIDI bridge
# depends only on this Protocol — agnostic to the device or software on the
# other end (Dubler 2, a keyboard, a controller, a DAW's virtual port, ...).

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class MIDISourceProtocol(Protocol):
    """Interface shared by the real MIDI source and StubMIDISource.

    A single long-running coroutine that pushes MIDI messages into a queue.
    The real implementation holds an open input port and feeds the queue from
    its notification callback; `interval` is a fallback cadence hint, mirroring
    HRMonitorProtocol.stream_hr.
    """

    async def stream_messages(self, queue: asyncio.Queue, interval: float = 1.0) -> None:
        """Stream MIDI messages into `queue` until cancelled."""
        ...


class MIDISource:
    """Real MIDI input source via mido (rtmidi backend).

    Opens an input port — by name if given, otherwise the first one mido
    reports — and pushes every incoming message into the queue via a
    notification callback, mirroring HRMonitor's bleak notify pattern. mido is
    lazy-imported in stream_messages so this module loads without it (e.g. CI).

    rtmidi invokes the callback on its own native thread, so the handler hops
    back onto the asyncio loop with call_soon_threadsafe before touching the
    queue — pushing from the wrong thread would corrupt asyncio.Queue's state.
    """

    def __init__(self, port_name: str | None = None) -> None:
        self._port_name = port_name

    def _make_callback(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        """Return a notification handler that hops onto the loop and enqueues."""

        def handler(message) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, message)

        return handler

    def _resolve_port_name(self, mido_module) -> str:
        """Return the configured port name, or the first one mido reports."""
        if self._port_name is not None:
            return self._port_name
        names = mido_module.get_input_names()
        if not names:
            raise RuntimeError("No MIDI input ports available")
        return names[0]

    async def stream_messages(self, queue: asyncio.Queue, interval: float = 1.0) -> None:
        """Open the port, subscribe to messages, and stream until cancelled."""
        import mido

        loop = asyncio.get_running_loop()
        name = self._resolve_port_name(mido)
        with mido.open_input(name, callback=self._make_callback(queue, loop)):
            # The callback drives the queue; just keep the port open.
            while True:
                await asyncio.sleep(interval)
