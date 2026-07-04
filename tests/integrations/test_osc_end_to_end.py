# End-to-end: the REAL python-osc server + client around a streaming engine.
#
# Everything else tests the engine through StubOSCServer.dispatch (same-thread,
# pre-run). This file closes the remaining gaps in one shot: the real OSCServer
# is constructed and served, the real OSCClient's wire format reaches the real
# dispatcher's handler call convention, and handlers mutate conditioning on the
# server thread WHILE the engine loop snapshots it — genuine cross-thread use.

import asyncio
import time

import pytest

pytest.importorskip("pythonosc")

from src.engine.fsm import State
from src.engine.rt2_engine import RT2Engine
from src.integrations.osc_client import OSCClient
from src.integrations.osc_server import OSCServer, OSCServerProtocol
from stubs.audio_sink_stub import NullAudioSink
from stubs.mrt2_client_stub import StubMRT2Client


async def _eventually(predicate, timeout=5.0, interval=0.01):
    """Poll until predicate() is true or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


def test_real_server_conforms_to_protocol():
    server = OSCServer(host="127.0.0.1", port=0)
    try:
        assert isinstance(server, OSCServerProtocol)
    finally:
        # NOT shutdown(): socketserver's shutdown blocks forever unless
        # serve_forever() is running. Just release the bound socket.
        server._server.server_close()


async def test_engine_driven_over_real_udp_while_streaming():
    server = OSCServer(host="127.0.0.1", port=0)  # ephemeral port
    port = server._server.server_address[1]
    client = OSCClient(host="127.0.0.1", port=port)
    mrt = StubMRT2Client()
    sink = NullAudioSink()
    engine = RT2Engine(mrt, sink, server)

    run_task = asyncio.create_task(engine.run())
    try:
        # Wait until the engine is actually streaming...
        assert await _eventually(lambda: sink.chunks_written >= 1)

        # ...then steer it over real UDP. Re-send while polling: latest-wins
        # semantics make duplicates harmless, and it derisks a dropped packet.
        def _landed():
            cond = mrt.conditioning or {}
            return cond.get("prompt") == "wire test" and cond.get("notes")

        while not _landed():
            client.send("/rt2/prompt", "wire test")
            client.send("/rt2/note/on", 61)
            await asyncio.sleep(0.02)
            if run_task.done():  # pragma: no cover - fail fast, not hang
                pytest.fail(f"engine exited early: {run_task.result()}")

        assert mrt.conditioning["prompt"] == "wire test"
        assert mrt.conditioning["notes"][61] in (1, 2)

        # A real /rt2/stop over the wire shuts the whole thing down cleanly.
        # (OSCSenderProtocol.send always carries one argument; stop ignores it.)
        client.send("/rt2/stop", 1)
        final = await asyncio.wait_for(run_task, timeout=5)
        assert final == State.IDLE
        assert sink.stopped is True
    finally:
        if not run_task.done():
            engine.stop()
            server.shutdown()
            await asyncio.wait_for(run_task, timeout=5)
