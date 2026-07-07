# Tests for the pure FSM core. The transition function is pure, so the whole
# (state, event) matrix is pinned here exhaustively: every legal pair, the
# universal ERROR event, and every remaining pair raising ValueError.

import pytest

from src.engine.fsm import Event, State, next_state

LEGAL = {
    (State.IDLE, Event.CONNECT): State.CONNECTING,
    (State.CONNECTING, Event.READY): State.STREAMING,
    (State.STREAMING, Event.TICK): State.GENERATING,
    (State.GENERATING, Event.CHUNK): State.STREAMING,
    (State.STREAMING, Event.STOP): State.IDLE,
    (State.ERROR, Event.RECOVER): State.IDLE,
}


def test_happy_path_cycle():
    assert next_state(State.IDLE, Event.CONNECT) == State.CONNECTING
    assert next_state(State.CONNECTING, Event.READY) == State.STREAMING
    assert next_state(State.STREAMING, Event.TICK) == State.GENERATING
    assert next_state(State.GENERATING, Event.CHUNK) == State.STREAMING


def test_stop_settles_streaming_to_idle():
    assert next_state(State.STREAMING, Event.STOP) == State.IDLE


def test_error_from_any_state():
    for state in State:
        assert next_state(state, Event.ERROR) == State.ERROR


def test_recover_from_error():
    assert next_state(State.ERROR, Event.RECOVER) == State.IDLE


@pytest.mark.parametrize("state", list(State))
@pytest.mark.parametrize("event", list(Event))
def test_full_matrix(state, event):
    """Every (state, event) pair: legal moves land, everything else raises."""
    if event == Event.ERROR:
        assert next_state(state, event) == State.ERROR
    elif (state, event) in LEGAL:
        assert next_state(state, event) == LEGAL[(state, event)]
    else:
        with pytest.raises(ValueError):
            next_state(state, event)
