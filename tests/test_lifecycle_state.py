"""Unit tests for the pure state -> button-view mapping."""

import pytest

from mcontrol import lifecycle_state


@pytest.mark.parametrize("state", ["created", "exited", "dead"])
def test_stopped_states_accent_start_disable_others(state):
    view = lifecycle_state.view(state)
    assert view["start_disabled"] is False
    assert view["stop_disabled"] is True
    assert view["restart_disabled"] is True
    assert view["accent"] == "start"


@pytest.mark.parametrize("state", ["running", "paused"])
def test_running_states_accent_stop_disable_start(state):
    view = lifecycle_state.view(state)
    assert view["start_disabled"] is True
    assert view["stop_disabled"] is False
    assert view["restart_disabled"] is False
    assert view["accent"] == "stop"


@pytest.mark.parametrize("state", ["restarting", "scaffolding"])
def test_transient_states_disable_all_no_accent(state):
    view = lifecycle_state.view(state)
    assert view["start_disabled"] is True
    assert view["stop_disabled"] is True
    assert view["restart_disabled"] is True
    assert view["accent"] is None


@pytest.mark.parametrize("state", ["unknown", "bogus", "", None])
def test_unrecognised_state_enables_all_no_accent(state):
    view = lifecycle_state.view(state)
    assert view["start_disabled"] is False
    assert view["stop_disabled"] is False
    assert view["restart_disabled"] is False
    assert view["accent"] is None
