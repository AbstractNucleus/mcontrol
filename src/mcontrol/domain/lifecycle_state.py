"""Pure state -> lifecycle-button-view mapping.

Single source of truth for "given a server's state, which of the three
lifecycle buttons (Start / Stop / Restart) is disabled, and which one
carries the `--accent` (the next-action CTA)."

Consumed by:
- `routes.server.server_detail`: to render the initial buttons.
- `routes.lifecycle.{start,stop,restart}`: to rebuild the buttons in
  the post-action OOB swap so the surface stays consistent.

Pins the state table.
"""

from typing import Literal, TypedDict

Accent = Literal["start", "stop", None]


class LifecycleView(TypedDict):
    start_disabled: bool
    stop_disabled: bool
    restart_disabled: bool
    accent: Accent
    compose_label: str | None


_RUNNING_LIKE = {"running", "paused"}
_STOPPED_LIKE = {"created", "exited", "dead", "missing"}
_TRANSIENT = {"restarting", "removing", "scaffolding"}
# mcontrol-specific lifecycle value: container is up but
# the listener port hasn't bound yet. Only ever written by the start
# handler on probe timeout, never returned by docker discovery.
_STARTING = "starting"


def is_running(server: dict) -> bool:
    """True when a server row's recorded state is exactly ``"running"``.

    Deliberately narrower than ``_RUNNING_LIKE``: callers gate live-only
    actions (RCON membership sync, the delete guard, the migrate
    warning) that a paused or transient container can't service.
    """
    return server.get("state") == "running"


def view(state: str | None) -> LifecycleView:
    """Map a server state string to the three buttons' view state.

    Unrecognised / `None` falls into a recovery posture: all buttons
    enabled, no accent. Discovery sometimes returns `"unknown"` when
    the Docker daemon is unreachable; the operator deserves the chance
    to attempt the action and let the route surface the real error.
    """
    if state in _STOPPED_LIKE:
        result: LifecycleView = {
            "start_disabled": False,
            "stop_disabled": True,
            "restart_disabled": True,
            "accent": "start",
            "compose_label": None,
        }
    elif state in _RUNNING_LIKE:
        result = {
            "start_disabled": True,
            "stop_disabled": False,
            "restart_disabled": False,
            "accent": "stop",
            "compose_label": None,
        }
    elif state == _STARTING:
        # Container is up; listener probe timed out.
        # Operator can Stop a stuck-start or Restart it; Start would be
        # a no-op. No accent. there's no obvious next action.
        result = {
            "start_disabled": True,
            "stop_disabled": False,
            "restart_disabled": False,
            "accent": None,
            "compose_label": None,
        }
    elif state in _TRANSIENT:
        result = {
            "start_disabled": True,
            "stop_disabled": True,
            "restart_disabled": True,
            "accent": None,
            "compose_label": None,
        }
    else:
        result = {
            "start_disabled": False,
            "stop_disabled": False,
            "restart_disabled": False,
            "accent": None,
            "compose_label": None,
        }
    if state == "exited":
        result["compose_label"] = "Apply compose"
    elif state in {"created", "missing"}:
        result["compose_label"] = "Create container"
    return result
