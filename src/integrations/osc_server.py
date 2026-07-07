# OSC server — the engine's inbound control surface.
#
# The RT2 engine (src/engine/rt2_engine.py) registers /rt2/* handlers on an
# OSCServerProtocol and lets it receive control messages from anything that
# speaks OSC: SuperCollider, Max/MSP, Pure Data, TouchOSC, or our own adapters
# (the MIDI and biometric bridges, over loopback UDP). Splitting this out of the
# engine keeps the wire transport reusable and dependency-light: the outbound
# OSC client (osc_client.py) shares the DEFAULT_HOST/PORT defined here without
# importing the engine.
#
# python-osc is lazy-imported in the real OSCServer so this module imports clean
# on CI (the stub path needs no network or python-osc).

from typing import Callable, Protocol, runtime_checkable

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5005


@runtime_checkable
class OSCServerProtocol(Protocol):
    """Interface shared by the real OSC server and StubOSCServer.

    The engine registers address handlers via map(), then serve() blocks
    receiving messages until shutdown() is called from another thread. Handlers
    are invoked as handler(address, *args), matching python-osc's dispatcher.
    """

    def map(self, address: str, handler: Callable[..., None]) -> None:
        """Route messages sent to `address` to `handler(address, *args)`."""
        ...

    def serve(self) -> None:
        """Block, dispatching incoming messages, until shutdown() is called."""
        ...

    def shutdown(self) -> None:
        """Unblock serve() and stop receiving. Safe to call from any thread."""
        ...


class OSCServer:
    """Real OSC server backed by python-osc (UDP).

    Lazy-imports python-osc in __init__ so this module stays importable without
    it (the stub path and CI never touch the network). Binds the socket on
    construction; serve() runs the blocking receive loop and shutdown() stops it.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import BlockingOSCUDPServer

        self._dispatcher = Dispatcher()
        self._server = BlockingOSCUDPServer((host, port), self._dispatcher)

    def map(self, address: str, handler: Callable[..., None]) -> None:
        """Register `handler` for `address`. python-osc calls it as (addr, *args)."""
        self._dispatcher.map(address, handler)

    def serve(self) -> None:
        """Run python-osc's blocking serve loop until shutdown()."""
        self._server.serve_forever()

    def shutdown(self) -> None:
        """Stop the serve loop and close the socket."""
        self._server.shutdown()
        self._server.server_close()
