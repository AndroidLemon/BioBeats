# Tests for the pipeline FSM core. The transition table is exhaustive and
# pure, so it is fully covered here without any async/hardware.

import asyncio

import pytest

from src.pipeline import (
    Event,
    PipelineContext,
    State,
    _next_latest_hr,
    next_state,
    run_pipeline,
)
from stubs.audio_sink_stub import NullAudioSink
from stubs.hr_monitor_stub import StubHRMonitor
from stubs.mrt2_client_stub import StubMRT2Client


def test_happy_path_cycle():
    assert next_state(State.IDLE, Event.CONNECT) == State.CONNECTING
    assert next_state(State.CONNECTING, Event.READY) == State.STREAMING
    assert next_state(State.STREAMING, Event.HR_TICK) == State.GENERATING
    assert next_state(State.GENERATING, Event.CHUNK) == State.STREAMING


def test_error_from_any_state():
    for state in State:
        assert next_state(state, Event.ERROR) == State.ERROR


def test_recover_from_error():
    assert next_state(State.ERROR, Event.RECOVER) == State.IDLE


def test_illegal_transition_raises():
    with pytest.raises(ValueError):
        next_state(State.IDLE, Event.CHUNK)
    with pytest.raises(ValueError):
        next_state(State.STREAMING, Event.READY)


async def test_pipeline_end_to_end_with_stubs():
    ctx = PipelineContext(
        hr_monitor=StubHRMonitor(),
        mrt=StubMRT2Client(),
        sink=NullAudioSink(),
        hr_queue=asyncio.Queue(),
        interval=0,
    )
    final = await run_pipeline(ctx)
    # Output wiring exercised end-to-end.
    assert ctx.sink.started and ctx.sink.stopped
    assert ctx.sink.chunks_written >= 1
    # Conditioning was derived from HR and pushed to the engine.
    assert ctx.mrt.conditioning is not None
    assert isinstance(ctx.mrt.conditioning["prompt"], str)
    # Ends back in STREAMING after a completed chunk.
    assert final == State.STREAMING


async def test_latest_hr_wins_on_drain():
    queue: asyncio.Queue = asyncio.Queue()
    for value in [100, 120, 150, 175]:
        queue.put_nowait(value)

    async def _noop() -> None:
        return None

    producer = asyncio.create_task(_noop())
    await producer
    latest = await _next_latest_hr(queue, producer)
    assert latest == 175
    assert queue.empty()
