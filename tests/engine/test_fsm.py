# Tests for the pure FSM core. The transition table is exhaustive and pure, so
# it is fully covered here with no async/hardware.

import pytest

from src.engine.fsm import Event, State, next_state


def test_happy_path_cycle():
    assert next_state(State.IDLE, Event.CONNECT) == State.CONNECTING
    assert next_state(State.CONNECTING, Event.READY) == State.STREAMING
    assert next_state(State.STREAMING, Event.TICK) == State.GENERATING
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
