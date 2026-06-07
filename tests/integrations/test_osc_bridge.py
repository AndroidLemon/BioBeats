# Tests for the OSC bridge: handler dispatch, latest-wins conditioning, and a
# full stub run (CI-safe — no network, no python-osc, no model, no audio device).

from src.integrations.osc_bridge import OSCBridge, OSCServerProtocol
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
