"""Shared operator-facing status names; Docker values stay unchanged on disk."""

LABELS = {
    "running": "Running",
    "starting": "Starting",
    "restarting": "Starting",
    "scaffolding": "Starting",
    "created": "Stopped",
    "exited": "Stopped",
    "paused": "Paused",
    "dead": "Failed",
    "removing": "Stopping",
    "missing": "Missing",
    "unknown": "Unavailable",
    "unreachable": "Unavailable",
}


def label(state: str | None) -> str:
    return LABELS.get(state, "Unavailable")
