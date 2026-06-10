# Pure FSM core for the RT2 engine lifecycle.
#
# The engine moves through exactly one state at a time: it connects (opens its
# control surface + sink, loads the model), streams, and generates one audio
# chunk per cadence tick, with a universal ERROR state and bounded recovery. The
# transition function is pure — no async, no I/O — so the whole lifecycle is
# exhaustively unit-testable. The imperative shell that drives it lives in the
# engine orchestrator (src/engine/rt2_engine.py).

import enum


class State(enum.Enum):
    """Engine FSM states. Exactly one is active at a time."""

    IDLE = enum.auto()
    CONNECTING = enum.auto()
    STREAMING = enum.auto()
    GENERATING = enum.auto()
    ERROR = enum.auto()


class Event(str, enum.Enum):
    """Events that drive state transitions."""

    CONNECT = "connect"
    READY = "ready"
    TICK = "tick"  # cadence boundary: time to generate the next chunk
    CHUNK = "chunk"
    ERROR = "error"
    RECOVER = "recover"


# Legal transitions, excluding the universal ERROR event handled below.
_TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.IDLE, Event.CONNECT): State.CONNECTING,
    (State.CONNECTING, Event.READY): State.STREAMING,
    (State.STREAMING, Event.TICK): State.GENERATING,
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
