# OSC sender — the loopback control-message client used by adapters (e.g. the
# MIDI and biometric bridges) to feed conditioning into a running RT2Engine.
#
# This keeps adapters "just another OSC client": they speak the same wire
# protocol and /rt2/* address space (see rt2_engine.py for the full channel
# list) as SuperCollider, Max/MSP, or TouchOSC would, over loopback UDP. No coupling
# to RT2Engine internals; swapping in a different control source means nothing
# in the engine has to change.
#
# python-osc is lazy-imported in the real OSCClient so this module stays
# importable on CI without it (the stub path needs no network).

from typing import Protocol, runtime_checkable

from src.integrations.osc_server import DEFAULT_HOST, DEFAULT_PORT


@runtime_checkable
class OSCSenderProtocol(Protocol):
    """Interface shared by the real OSC client and StubOSCClient."""

    def send(self, address: str, value) -> None:
        """Send an OSC message carrying one argument to `address`."""
        ...


class OSCClient:
    """Real OSC sender backed by python-osc (UDP).

    Lazy-imports python-osc in __init__ so this module stays importable
    without it. UDP is connectionless, so construction never blocks or fails
    on a missing listener — sends are fire-and-forget, matching the advisory,
    latest-wins nature of RT2 conditioning.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        from pythonosc.udp_client import SimpleUDPClient

        self._client = SimpleUDPClient(host, port)

    def send(self, address: str, value) -> None:
        """Send `value` as the single argument of an OSC message to `address`."""
        self._client.send_message(address, value)
