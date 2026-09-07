"""Unit tests for the pure state -> button-view mapping."""

import pytest

from mcontrol.domain import lifecycle_state


@pytest.mark.parametrize("state", ["created", "exited", "dead", "missing"])
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


@pytest.mark.parametrize("state", ["restarting", "removing", "scaffolding"])
def test_transient_states_disable_all_no_accent(state):
    view = lifecycle_state.view(state)
    assert view["start_disabled"] is True
    assert view["stop_disabled"] is True
    assert view["restart_disabled"] is True
    assert view["accent"] is None


def test_starting_state_keeps_stop_and_restart_reachable():
    """'starting' means the container is up but the listener hasn't
    bound. Operator can Stop a stuck-start or Restart it; Start would
    be a no-op."""
    view = lifecycle_state.view("starting")
    assert view["start_disabled"] is True
    assert view["stop_disabled"] is False
    assert view["restart_disabled"] is False
    assert view["accent"] is None


@pytest.mark.parametrize("state", ["unknown", "bogus", "", None])
def test_unrecognised_state_enables_all_no_accent(state):
    view = lifecycle_state.view(state)
    assert view["start_disabled"] is False
    assert view["stop_disabled"] is False
    assert view["restart_disabled"] is False
    assert view["accent"] is None


def test_compose_label_for_created_and_missing():
    assert lifecycle_state.view("created")["compose_label"] == "Create container"
    assert lifecycle_state.view("missing")["compose_label"] == "Create container"


def test_compose_label_for_exited():
    assert lifecycle_state.view("exited")["compose_label"] == "Apply compose"


@pytest.mark.parametrize("state", ["running", "starting", "dead", None])
def test_compose_label_absent_for_other_states(state):
    assert lifecycle_state.view(state)["compose_label"] is None
