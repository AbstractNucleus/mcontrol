"""Pure state -> lifecycle-button-view mapping.

Single source of truth for "given a server's state, which of the three
lifecycle buttons (Start / Stop / Restart) is disabled, and which one
carries the `--accent` (the next-action CTA)."

Consumed by:
- `routes.server.server_detail` — to render the initial buttons.
- `routes.lifecycle.{start,stop,restart}` — to rebuild the buttons in
  the post-action OOB swap so the surface stays consistent.

Slice 13 / decision 033. The slice 12 plan deferred this; this module
pins the state table.
"""

from typing import Literal, TypedDict

Accent = Literal["start", "stop", None]


class LifecycleView(TypedDict):
    start_disabled: bool
    stop_disabled: bool
    restart_disabled: bool
    accent: Accent


_RUNNING_LIKE = {"running", "paused"}
_STOPPED_LIKE = {"created", "exited", "dead"}
_TRANSIENT = {"restarting", "scaffolding"}


def view(state: str | None) -> LifecycleView:
    """Map a server state string to the three buttons' view state.

    Unrecognised / `None` falls into a recovery posture: all buttons
    enabled, no accent. Discovery sometimes returns `"unknown"` when
    the Docker daemon is unreachable; the operator deserves the chance
    to attempt the action and let the route surface the real error.
    """
    if state in _STOPPED_LIKE:
        return {
            "start_disabled": False,
            "stop_disabled": True,
            "restart_disabled": True,
            "accent": "start",
        }
    if state in _RUNNING_LIKE:
        return {
            "start_disabled": True,
            "stop_disabled": False,
            "restart_disabled": False,
            "accent": "stop",
        }
    if state in _TRANSIENT:
        return {
            "start_disabled": True,
            "stop_disabled": True,
            "restart_disabled": True,
            "accent": None,
        }
    return {
        "start_disabled": False,
        "stop_disabled": False,
        "restart_disabled": False,
        "accent": None,
    }
