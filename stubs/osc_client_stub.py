# Stub for src/integrations/osc_client.py's OSCSenderProtocol.
# StubOSCClient needs no network and no python-osc: it just records every send
# as an (address, value) pair so tests can assert on what the bridge forwarded.

class StubOSCClient:
    """In-process OSC sender stand-in. No sockets, no python-osc.

    Records every send() call so tests can inspect what would have gone out.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    def send(self, address: str, value) -> None:
        """Record the (address, value) pair instead of sending it anywhere."""
        self.sent.append((address, value))
