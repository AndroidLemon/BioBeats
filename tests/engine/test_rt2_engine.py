# Tests for the RT2 engine: handler dispatch, the per-chunk conditioning
# snapshot (style/intensity + sparse notes/drums/CFG), FSM-driven streaming,
# bounded error recovery, and server-death termination (CI-safe — no network,
# no python-osc, no model, no audio device).

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


def test_registers_all_control_handlers():
    _, _, _, server = _make_engine()
    assert set(server.handlers) == {
        "/rt2/prompt",
        "/rt2/intensity",
        "/rt2/note/on",
        "/rt2/note/off",
        "/rt2/drum",
        "/rt2/cfg/notes",
        "/rt2/cfg/drums",
    }


# --- style / intensity -----------------------------------------------------


def test_prompt_message_updates_snapshot():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/prompt", "techno bass")
    assert engine._snapshot_conditioning()["prompt"] == "techno bass"


def test_intensity_message_is_clamped():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/intensity", 2.5)
    assert engine._snapshot_conditioning()["intensity"] == 1.0
    server.dispatch("/rt2/intensity", -0.5)
    assert engine._snapshot_conditioning()["intensity"] == 0.0


# --- sparse notes ----------------------------------------------------------


def test_no_notes_held_is_masked():
    engine, _, _, _ = _make_engine()
    assert engine._snapshot_conditioning()["notes"] is None


def test_note_on_is_onset_then_continuation():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/note/on", 60)

    first = engine._snapshot_conditioning()["notes"]
    assert first[60] == 2  # struck this chunk -> onset
    assert sum(first) == 2  # only pitch 60 is active

    second = engine._snapshot_conditioning()["notes"]
    assert second[60] == 1  # still held -> continuation

    server.dispatch("/rt2/note/off", 60)
    assert engine._snapshot_conditioning()["notes"] is None  # nothing held -> masked


def test_chord_marks_all_onsets():
    engine, _, _, server = _make_engine()
    for pitch in (60, 64, 67):
        server.dispatch("/rt2/note/on", pitch)
    notes = engine._snapshot_conditioning()["notes"]
    assert notes[60] == notes[64] == notes[67] == 2


def test_tap_within_one_chunk_still_registers_onset():
    # Pressed and released before the snapshot: the onset for that chunk stands.
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/note/on", 72)
    server.dispatch("/rt2/note/off", 72)
    first = engine._snapshot_conditioning()["notes"]
    assert first[72] == 2
    # ...but it isn't held, so the next chunk is masked again.
    assert engine._snapshot_conditioning()["notes"] is None


def test_out_of_range_pitches_are_ignored():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/note/on", 200)
    server.dispatch("/rt2/note/on", -1)
    assert engine._snapshot_conditioning()["notes"] is None


# --- drums / cfg -----------------------------------------------------------


def test_drum_state_threads_into_snapshot():
    engine, _, _, server = _make_engine()
    assert engine._snapshot_conditioning()["drums"] is None  # -1 masked by default
    server.dispatch("/rt2/drum", 1)
    assert engine._snapshot_conditioning()["drums"] == [1]
    server.dispatch("/rt2/drum", 0)
    assert engine._snapshot_conditioning()["drums"] == [0]


def test_cfg_scales_are_set_and_clamped():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/cfg/notes", 4.0)
    server.dispatch("/rt2/cfg/drums", 99.0)  # clamps to 7.0
    snap = engine._snapshot_conditioning()
    assert snap["cfg_notes"] == 4.0
    assert snap["cfg_drums"] == 7.0


def test_malformed_messages_do_not_raise():
    engine, _, _, server = _make_engine()
    server.dispatch("/rt2/prompt")  # no arg
    server.dispatch("/rt2/intensity", "loud")  # non-numeric
    server.dispatch("/rt2/note/on")  # no arg
    server.dispatch("/rt2/note/on", "x")  # non-integer
    server.dispatch("/rt2/note/on", 60.5)  # float pitch -> ignored, not truncated
    server.dispatch("/rt2/drum", 1.9)  # float -> ignored, not truncated to 1
    server.dispatch("/rt2/cfg/notes", "x")  # non-numeric
    snap = engine._snapshot_conditioning()
    assert snap["notes"] is None and snap["cfg_notes"] is None
    assert snap["drums"] is None


# --- run loop --------------------------------------------------------------


async def test_run_streams_chunks_and_settles_idle():
    engine, mrt, sink, server = _make_engine()
    server.dispatch("/rt2/prompt", "ambient drone")
    server.dispatch("/rt2/note/on", 60)
    final = await engine.run(max_chunks=2)
    assert final == State.IDLE  # a clean stop settles the FSM
    assert sink.started and sink.stopped
    assert sink.chunks_written == 2
    # The latest snapshot reached the model: prompt + the held note.
    assert mrt.conditioning["prompt"] == "ambient drone"
    assert mrt.conditioning["notes"][60] in (1, 2)


async def test_stop_terminates_unbounded_run():
    engine, _, sink, _ = _make_engine()

    original_write = sink.write

    def write_and_stop(samples):
        original_write(samples)
        engine.stop()  # a control surface (or signal handler) pulls the plug

    sink.write = write_and_stop
    final = await asyncio.wait_for(engine.run(), timeout=5)
    assert final == State.IDLE
    assert sink.chunks_written == 1
    assert sink.stopped is True


async def test_run_pushes_default_prompt_without_osc():
    engine, mrt, _, _ = _make_engine(default_prompt="seed pad")
    await engine.run(max_chunks=1)
    assert mrt.conditioning["prompt"] == "seed pad"


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
    assert final == State.IDLE
    assert mrt.calls == 4  # 1 initial + 3 retries
    assert sink.stopped is True
    assert "engine failed after 3 retries" in caplog.text


class _DyingOSCServer(StubOSCServer):
    """OSC server whose serve() fails immediately, as a bind/receive error would."""

    def serve(self) -> None:
        raise RuntimeError("bind failed")


async def test_server_death_is_an_error_not_a_clean_stop(caplog):
    mrt = StubMRT2Client()
    sink = NullAudioSink()
    engine = RT2Engine(mrt, sink, _DyingOSCServer())
    final = await asyncio.wait_for(engine.run(), timeout=5)
    # A dead control surface is a failure: the FSM goes through ERROR and
    # settles in IDLE, and the failure is logged — never a silent STREAMING.
    assert final == State.IDLE
    assert sink.stopped is True
    assert "control surface died" in caplog.text
    assert "OSC server thread failed" in caplog.text


class _CongestedSink(NullAudioSink):
    """Sink that reports a deep playback backlog for its first few polls."""

    def __init__(self) -> None:
        super().__init__()
        self.polls = 0

    def buffered_frames(self) -> int:
        self.polls += 1
        return 10_000_000 if self.polls < 3 else 0


async def test_generation_paces_against_playback_backlog():
    # With more than TARGET_BUFFER_CHUNKS queued, the engine must wait instead
    # of generating further ahead (unbounded backlog = unbounded control
    # latency). The congested sink clears after two polls; both chunks land.
    mrt = StubMRT2Client()
    sink = _CongestedSink()
    engine = RT2Engine(mrt, sink, StubOSCServer())
    final = await asyncio.wait_for(engine.run(max_chunks=2), timeout=5)
    assert final == State.IDLE
    assert sink.chunks_written == 2
    assert sink.polls >= 3  # it actually waited on the backlog


class _SlowTinyChunkClient(StubMRT2Client):
    """Generates a tiny chunk slower than its own real-time budget."""

    def generate_chunk(self):
        import time

        time.sleep(0.01)  # far longer than 10 frames / 48kHz
        import numpy as np

        return np.zeros((10, 2), dtype=np.float32)


async def test_slower_than_realtime_generation_logs_warning(caplog):
    engine = RT2Engine(_SlowTinyChunkClient(), NullAudioSink(), StubOSCServer())
    await engine.run(max_chunks=1)
    assert "slower than real time" in caplog.text
    assert engine.last_gen_seconds is not None and engine.last_gen_seconds > 0
