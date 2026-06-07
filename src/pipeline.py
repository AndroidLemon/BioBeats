# FSM orchestrator for the biometric -> generative-music pipeline.
#
# This module is split into a functional core (the pure `next_state` transition
# function and the State/Event enums) and an imperative shell (the async
# `run_pipeline`, added later) that performs all I/O. Keeping transitions pure
# makes the FSM exhaustively unit-testable with no async or hardware.

import enum


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
