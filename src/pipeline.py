# FSM orchestrator for the biometric -> generative-music pipeline.
#
# This module is split into a functional core (the pure `next_state` transition
# function and the State/Event enums) and an imperative shell (the async
# `run_pipeline`, added later) that performs all I/O. Keeping transitions pure
# makes the FSM exhaustively unit-testable with no async or hardware.

import asyncio
import enum
from dataclasses import dataclass

from src.ble.hr_monitor import HRMonitorProtocol
from src.engine.mrt2_client import MRT2ClientProtocol
from src.mapping.hr_to_prompt import hr_to_conditioning
from src.output.audio_sink import AudioSinkProtocol


class State(enum.Enum):
    """Pipeline FSM states. Exactly one is active at a time."""

    IDLE = enum.auto()
    CONNECTING = enum.auto()
    STREAMING = enum.auto()
    GENERATING = enum.auto()
    ERROR = enum.auto()


class Event(str, enum.Enum):
    """Events that drive state transitions."""

    CONNECT = "connect"
    READY = "ready"
    HR_TICK = "hr_tick"
    CHUNK = "chunk"
    ERROR = "error"
    RECOVER = "recover"


# Legal transitions, excluding the universal ERROR event handled below.
_TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.IDLE, Event.CONNECT): State.CONNECTING,
    (State.CONNECTING, Event.READY): State.STREAMING,
    (State.STREAMING, Event.HR_TICK): State.GENERATING,
    (State.GENERATING, Event.CHUNK): State.STREAMING,
    (State.ERROR, Event.RECOVER): State.IDLE,
}


def next_state(current: State, event: Event) -> State:
    """Return the next state for (current, event). Pure — no side effects.

    An ERROR event transitions to ERROR from any state. Any other
    (state, event) pair not in the transition table is illegal and raises
    ValueError.
    """
    if event == Event.ERROR:
        return State.ERROR
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError:
        raise ValueError(
            f"illegal transition: {current.name} --{Event(event).value}-->"
        ) from None


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


async def run_pipeline(ctx: PipelineContext) -> State:
    """Drive the pipeline: HR -> mapping -> conditioning -> audio chunk -> sink.

    Imperative shell. Spawns the HR producer, then loops: take the latest HR,
    update conditioning, generate one chunk off-thread (the model call is
    blocking), and write it to the sink. Terminates when the HR source ends and
    the queue is drained. Returns the final FSM state.
    """
    state = State.IDLE
    ctx.sink.start()
    state = next_state(state, Event.CONNECT)  # -> CONNECTING
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
            state = next_state(state, Event.HR_TICK)  # -> GENERATING
            ctx.mrt.update_conditioning(hr_to_conditioning(hr, ctx.hr_max))
            # The model call blocks (JAX/MLX); keep the event loop responsive.
            chunk = await asyncio.to_thread(ctx.mrt.generate_chunk)
            ctx.sink.write(chunk)
            state = next_state(state, Event.CHUNK)  # -> STREAMING
    finally:
        if not hr_task.done():
            hr_task.cancel()
        ctx.sink.stop()
    return state
