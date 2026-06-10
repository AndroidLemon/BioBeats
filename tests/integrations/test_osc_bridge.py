# Tests for the OSC bridge: handler dispatch, latest-wins conditioning, malformed
# message handling, server-death termination, and a full stub run (CI-safe — no
# network, no python-osc, no model, no audio device).

import asyncio

from src.integrations.osc_bridge import OSCBridge
from src.integrations.osc_server import OSCServerProtocol
from stubs.audio_sink_stub import NullAudioSink
from stubs.mrt2_client_stub import StubMRT2Client
from stubs.osc_server_stub import StubOSCServer


def _make_bridge(**kwargs):
    mrt = StubMRT2Client()
    sink = NullAudioSink()
    server = StubOSCServer()
    bridge = OSCBridge(mrt, sink, server, **kwargs)
    return bridge, mrt, sink, server


def test_stub_server_satisfies_protocol():
    assert isinstance(StubOSCServer(), OSCServerProtocol)


def test_registers_handlers_on_construction():
    _, _, _, server = _make_bridge()
    assert "/rt2/prompt" in server.handlers
    assert "/rt2/intensity" in server.handlers


def test_prompt_message_updates_conditioning():
    bridge, _, _, server = _make_bridge()
    server.dispatch("/rt2/prompt", "techno bass")
    assert bridge._take_conditioning()["prompt"] == "techno bass"


def test_intensity_message_updates_conditioning():
    bridge, _, _, server = _make_bridge()
    server.dispatch("/rt2/intensity", 0.75)
    assert bridge._take_conditioning()["intensity"] == 0.75


def test_take_conditioning_is_latest_wins():
    bridge, _, _, server = _make_bridge()
    bridge._take_conditioning()  # clear the initial default
    server.dispatch("/rt2/prompt", "one")
    server.dispatch("/rt2/prompt", "two")
    server.dispatch("/rt2/prompt", "three")
    taken = bridge._take_conditioning()
    assert taken["prompt"] == "three"
    # Nothing new since: a second take yields None (no redundant re-embed).
    assert bridge._take_conditioning() is None


async def test_run_streams_chunks_and_applies_osc_prompt():
    bridge, mrt, sink, server = _make_bridge()
    server.dispatch("/rt2/prompt", "ambient drone")
    produced = await bridge.run(max_chunks=2)
    assert produced == 2
    assert sink.started and sink.stopped
    assert sink.chunks_written == 2
    # The OSC-sent prompt reached the model.
    assert mrt.conditioning["prompt"] == "ambient drone"


async def test_run_pushes_default_conditioning_without_osc():
    bridge, mrt, sink, _ = _make_bridge(default_prompt="seed pad")
    await bridge.run(max_chunks=1)
    assert mrt.conditioning["prompt"] == "seed pad"


def test_malformed_messages_do_not_raise():
    # Empty/bad OSC args must not crash the server thread; they are ignored,
    # leaving conditioning unchanged (only the initial default stays dirty).
    bridge, _, _, server = _make_bridge()
    bridge._take_conditioning()  # clear the initial default
    server.dispatch("/rt2/prompt")  # no argument
    server.dispatch("/rt2/intensity")  # no argument
    server.dispatch("/rt2/intensity", "loud")  # non-numeric
    assert bridge._take_conditioning() is None


def test_intensity_is_clamped_to_unit_range():
    bridge, _, _, server = _make_bridge()
    server.dispatch("/rt2/intensity", 2.5)
    assert bridge._take_conditioning()["intensity"] == 1.0
    server.dispatch("/rt2/intensity", -0.5)
    assert bridge._take_conditioning()["intensity"] == 0.0


class _DyingOSCServer(StubOSCServer):
    """OSC server whose serve() fails immediately, as a bind/receive error would."""

    def serve(self) -> None:
        raise RuntimeError("bind failed")


async def test_run_stops_and_surfaces_server_thread_failure(caplog):
    mrt = StubMRT2Client()
    sink = NullAudioSink()
    bridge = OSCBridge(mrt, sink, _DyingOSCServer())
    # No max_chunks: the loop must terminate on its own when the server dies.
    await asyncio.wait_for(bridge.run(), timeout=5)
    assert sink.stopped is True
    assert "OSC server thread failed" in caplog.text
