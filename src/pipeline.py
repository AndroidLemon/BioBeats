# FSM orchestrator for the biometric -> generative-music pipeline.
#
# This module is split into a functional core (the pure `next_state` transition
# function and the State/Event enums) and an imperative shell (the async
# `run_pipeline`, added later) that performs all I/O. Keeping transitions pure
# makes the FSM exhaustively unit-testable with no async or hardware.

import asyncio
import logging
from dataclasses import dataclass

from src.ble.hr_monitor import HRMonitorProtocol
from src.engine.fsm import Event, State, next_state
from src.engine.mrt2_client import MRT2ClientProtocol
from src.mapping.hr_to_prompt import hr_to_conditioning
from src.output.audio_sink import AudioSinkProtocol

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Everything run_pipeline needs, injected explicitly (no global state).

    Tests pass stub collaborators; the entrypoint passes real ones. All three
    collaborators are referenced only through their Protocols.
    """

    hr_monitor: HRMonitorProtocol
    mrt: MRT2ClientProtocol
    sink: AudioSinkProtocol
    hr_queue: asyncio.Queue
    hr_max: int = 185
    interval: float = 1.0


async def _next_latest_hr(queue: asyncio.Queue, producer: asyncio.Task):
    """Return the most recent HR reading, or None if the producer is finished
    and the queue is drained.

    Only the latest reading matters at a chunk boundary, so stale readings are
    discarded. Blocks until a reading is available or the producer completes.
    """
    if queue.empty():
        if producer.done():
            return None
        get_task = asyncio.ensure_future(queue.get())
        done, _ = await asyncio.wait(
            {get_task, producer}, return_when=asyncio.FIRST_COMPLETED
        )
        if get_task in done:
            latest = get_task.result()
        else:
            get_task.cancel()
            if queue.empty():
                return None
            latest = queue.get_nowait()
    else:
        latest = queue.get_nowait()
    # Drain any readings that piled up; keep only the freshest.
    while not queue.empty():
        latest = queue.get_nowait()
    return latest


async def _run_session(ctx: PipelineContext) -> State:
    """Run one connect -> stream -> generate cycle. Returns the final state.

    Spawns the HR producer, then loops: take the latest HR, update
    conditioning, generate one chunk off-thread (the model call is blocking),
    and write it to the sink. Terminates when the HR source ends and the queue
    is drained. Raises if any collaborator (producer included) fails.
    """
    state = next_state(State.IDLE, Event.CONNECT)  # -> CONNECTING
    hr_task = asyncio.create_task(ctx.hr_monitor.stream_hr(ctx.hr_queue, ctx.interval))
    ready = False
    try:
        while True:
            hr = await _next_latest_hr(ctx.hr_queue, hr_task)
            if hr is None:
                break
            if not ready:
                state = next_state(state, Event.READY)  # -> STREAMING
                ready = True
            state = next_state(state, Event.TICK)  # -> GENERATING
            ctx.mrt.update_conditioning(hr_to_conditioning(hr, ctx.hr_max))
            # The model call blocks (JAX/MLX); keep the event loop responsive.
            chunk = await asyncio.to_thread(ctx.mrt.generate_chunk)
            ctx.sink.write(chunk)
            state = next_state(state, Event.CHUNK)  # -> STREAMING
        # Surface a producer failure that ended the stream.
        if hr_task.done() and not hr_task.cancelled() and hr_task.exception():
            raise hr_task.exception()
        return state
    finally:
        if not hr_task.done():
            hr_task.cancel()


async def run_pipeline(ctx: PipelineContext, max_retries: int = 3) -> State:
    """Drive the pipeline with bounded error recovery. Returns the final state.

    On a collaborator failure the FSM enters ERROR and recovers (-> IDLE) for
    another attempt, up to `max_retries` times. After that it surfaces the
    error and settles in IDLE rather than looping forever (AGENTS.md rule).
    """
    ctx.sink.start()
    state = State.IDLE
    attempt = 0
    try:
        while True:
            try:
                state = await _run_session(ctx)
                return state
            except Exception as exc:  # noqa: BLE001 - boundary: any failure -> ERROR
                state = next_state(state, Event.ERROR)  # -> ERROR
                if attempt >= max_retries:
                    logger.error(
                        "pipeline failed after %d retries: %r", max_retries, exc
                    )
                    return next_state(state, Event.RECOVER)  # -> IDLE
                attempt += 1
                state = next_state(state, Event.RECOVER)  # -> IDLE, retry
    finally:
        ctx.sink.stop()
