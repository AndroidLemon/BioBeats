# Tests for the RT2 engine: handler dispatch, latest-wins conditioning, malformed
# message handling, FSM-driven streaming, bounded error recovery, and server-death
# termination (CI-safe — no network, no python-osc, no model, no audio device).

import asyncio

from src.engine.fsm import State
from src.engine.rt2_engine import RT2Engine
from src.integrations.osc_server import OSCServerProtocol
from stubs.audio_sink_stub import NullAudioSink
from stubs.mrt2_client_stub import StubMRT2Client
from stubs.osc_server_stub import StubOSCServer


def _make_engine(**kwargs):
    mrt = StubMRT2Client()
    sink = NullAudioSink()
    server = StubOSCServer()
    engine = RT2Engine(mrt, sink, server, **kwargs)
    return engine, mrt, sink, server


def test_stub_server_satisfies_protocol():
    assert isinstance(StubOSCServer(), OSCServerProtocol)


def test_registers_handlers_on_construction():
    _, _, _, server = _make_engine()
    assert "/rt2/prompt" in server.handlers
    assert "/rt2/intensity" in server.handlers


def test_prompt_message_updates_conditioning():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/prompt", "techno bass")
    assert engine._take_conditioning()["prompt"] == "techno bass"


def test_intensity_message_updates_conditioning():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/intensity", 0.75)
    assert engine._take_conditioning()["intensity"] == 0.75


def test_take_conditioning_is_latest_wins():
    engine, _, _, server = _make_engine()
    engine._take_conditioning()  # clear the initial default
    server.dispatch("/rt2/prompt", "one")
    server.dispatch("/rt2/prompt", "two")
    server.dispatch("/rt2/prompt", "three")
    taken = engine._take_conditioning()
    assert taken["prompt"] == "three"
    # Nothing new since: a second take yields None (no redundant re-embed).
    assert engine._take_conditioning() is None


async def test_run_streams_chunks_and_applies_osc_prompt():
    engine, mrt, sink, server = _make_engine()
    server.dispatch("/rt2/prompt", "ambient drone")
    final = await engine.run(max_chunks=2)
    # Clean end after streaming settles back in STREAMING.
    assert final == State.STREAMING
    assert sink.started and sink.stopped
    assert sink.chunks_written == 2
    # The OSC-sent prompt reached the model.
    assert mrt.conditioning["prompt"] == "ambient drone"


async def test_run_pushes_default_conditioning_without_osc():
    engine, mrt, sink, _ = _make_engine(default_prompt="seed pad")
    await engine.run(max_chunks=1)
    assert mrt.conditioning["prompt"] == "seed pad"


def test_malformed_messages_do_not_raise():
    # Empty/bad OSC args must not crash the server thread; they are ignored,
    # leaving conditioning unchanged (only the initial default stays dirty).
    engine, _, _, server = _make_engine()
    engine._take_conditioning()  # clear the initial default
    server.dispatch("/rt2/prompt")  # no argument
    server.dispatch("/rt2/intensity")  # no argument
    server.dispatch("/rt2/intensity", "loud")  # non-numeric
    assert engine._take_conditioning() is None


def test_intensity_is_clamped_to_unit_range():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/intensity", 2.5)
    assert engine._take_conditioning()["intensity"] == 1.0
    server.dispatch("/rt2/intensity", -0.5)
    assert engine._take_conditioning()["intensity"] == 0.0


class _FailingMRT2Client:
    """MRT2 stub whose generate_chunk always raises; counts attempts."""

    def __init__(self) -> None:
        self.calls = 0

    def update_conditioning(self, conditioning: dict) -> None:
        pass

    def generate_chunk(self):
        self.calls += 1
        raise RuntimeError("model exploded")


async def test_generation_failure_retries_then_settles_idle(caplog):
    mrt = _FailingMRT2Client()
    sink = NullAudioSink()
    final = await RT2Engine(mrt, sink, StubOSCServer()).run(max_retries=3)
    # Settles in IDLE after exhausting retries.
    assert final == State.IDLE
    # 1 initial attempt + 3 retries = 4 generate_chunk calls.
    assert mrt.calls == 4
    # Sink released, error surfaced (not silently swallowed).
    assert sink.stopped is True
    assert "engine failed after 3 retries" in caplog.text


class _DyingOSCServer(StubOSCServer):
    """OSC server whose serve() fails immediately, as a bind/receive error would."""

    def serve(self) -> None:
        raise RuntimeError("bind failed")


async def test_run_stops_and_surfaces_server_thread_failure(caplog):
    mrt = StubMRT2Client()
    sink = NullAudioSink()
    engine = RT2Engine(mrt, sink, _DyingOSCServer())
    # No max_chunks: the loop must terminate on its own when the server dies.
    await asyncio.wait_for(engine.run(), timeout=5)
    assert sink.stopped is True
    assert "OSC server thread failed" in caplog.text
