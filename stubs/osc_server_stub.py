# Stub for src/integrations/osc_server.py's OSCServerProtocol.
# StubOSCServer needs no network and no python-osc: it records handler maps and
# lets tests inject messages directly via dispatch(), so the OSC bridge can be
# exercised end-to-end on CI. serve() blocks (like the real receive loop) until
# shutdown() is called, mirroring the real start/stop lifecycle.

import threading
from typing import Callable


class StubOSCServer:
    """In-process OSC server stand-in. No sockets, no python-osc.

    Holds the address->handler map and exposes dispatch() so tests can simulate
    an incoming OSC message by calling the registered handler directly. serve()
    blocks on an event until shutdown(), matching the real server's lifecycle.
    """

    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., None]] = {}
        self._stop = threading.Event()

    def map(self, address: str, handler: Callable[..., None]) -> None:
        """Record the handler for an address."""
        self.handlers[address] = handler

    def dispatch(self, address: str, *args) -> None:
        """Simulate an incoming OSC message: invoke the registered handler."""
        self.handlers[address](address, *args)

    def serve(self) -> None:
        """Block until shutdown() is called, like the real receive loop."""
        self._stop.wait()

    def shutdown(self) -> None:
        """Unblock serve()."""
        self._stop.set()
