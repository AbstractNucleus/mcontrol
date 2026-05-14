"""Shared form validator for the server-variables field set.

Used by routes/new_server.py, routes/migrate.py, and routes/variables.py,
all of which accept the same (memory_budget_gb, port, server_jar,
jvm_extra_args) fields with the same rules.
"""

import socket

from mcontrol import db

PORT_MIN = 1024
PORT_MAX = 65535
MEMORY_MIN_GB = 2
_PORT_PROBE_TIMEOUT = 0.5


def validate(form: dict) -> dict[str, str]:
    """Validate the variables fields. No DB or disk lookups."""
    errors: dict[str, str] = {}
    if form["memory_budget_gb"] < MEMORY_MIN_GB:
        errors["memory_budget_gb"] = f"Minimum {MEMORY_MIN_GB} GB."
    if not (PORT_MIN <= form["port"] <= PORT_MAX):
        errors["port"] = f"Port must be between {PORT_MIN} and {PORT_MAX}."
    if not form["server_jar"].strip():
        errors["server_jar"] = "Required."
    return errors


def check_port_collision(exclude_name: str | None, port: int) -> str | None:
    """Return an error string if *port* is already used by another server.

    Pass *exclude_name* as the current server's name so a server can keep
    its own port without triggering a false collision. Pass ``None`` for
    new-server forms where no existing row should be excluded.
    """
    for row in db.list_servers():
        if exclude_name is not None and row["name"] == exclude_name:
            continue
        row_vars = row.get("variables") or {}
        if row_vars.get("port") == port:
            return f"Port {port} is already used by '{row['name']}'."
    return None


def check_port_bound(port: int) -> str | None:
    """Return an error string if something on the host is already
    listening on *port*. Catches collisions with non-mcontrol services
    that ``check_port_collision`` can't see (issue #124).
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_PORT_PROBE_TIMEOUT):
            return f"Port {port} is already bound on this host."
    except OSError:
        return None
