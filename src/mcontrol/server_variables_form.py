"""Shared form validator for the server-variables field set.

Used by routes/new_server.py, routes/migrate.py, and routes/variables.py,
all of which accept the same (memory_budget_gb, port, server_jar,
jvm_extra_args) fields with the same rules.
"""

import socket
from typing import Literal

from mcontrol import db_async

PORT_MIN = 1024
PORT_MAX = 65535
MEMORY_MIN_GB = 2
_PORT_PROBE_TIMEOUT = 0.5

# Loader enum, mirroring app_mcontrol.servers.loader in supabase-server.
# Order is significant for `infer_loader_from_jar`: forge → fabric →
# paper → quilt → vanilla, first match wins. Vanilla is the fallback
# and never matches by name (no jar filename contains "vanilla" reliably).
LOADERS: tuple[str, ...] = ("vanilla", "forge", "fabric", "paper", "quilt")
Loader = Literal["vanilla", "forge", "fabric", "paper", "quilt"]
_INFER_ORDER: tuple[str, ...] = ("forge", "fabric", "paper", "quilt")


def infer_loader_from_jar(server_jar: str) -> Loader:
    """Best-effort guess of the loader from the jar filename.

    Mirrors the supabase-server backfill rule (AbstractNucleus/supabase-server#8):
    case-insensitive substring match in `forge → fabric → paper → quilt`
    order, vanilla as the fallback. New-server form submissions do NOT
    call this — the operator's dropdown choice is authoritative there.
    Kept here so future callers (legacy-row backfill, migrate flow) share
    one rule with the DB-side backfill.
    """
    needle = server_jar.lower()
    for loader in _INFER_ORDER:
        if loader in needle:
            return loader  # type: ignore[return-value]
    return "vanilla"


def validate(form: dict) -> dict[str, str]:
    """Validate the variables fields. No DB or disk lookups."""
    errors: dict[str, str] = {}
    if form["memory_budget_gb"] < MEMORY_MIN_GB:
        errors["memory_budget_gb"] = f"Minimum {MEMORY_MIN_GB} GB."
    if not (PORT_MIN <= form["port"] <= PORT_MAX):
        errors["port"] = f"Port must be between {PORT_MIN} and {PORT_MAX}."
    if not form["server_jar"].strip():
        errors["server_jar"] = "Required."
    if "loader" in form and form["loader"] not in LOADERS:
        errors["loader"] = f"Must be one of: {', '.join(LOADERS)}."
    return errors


async def check_port_collision(exclude_name: str | None, port: int) -> str | None:
    """Return an error string if *port* is already used by another server.

    Pass *exclude_name* as the current server's name so a server can keep
    its own port without triggering a false collision. Pass ``None`` for
    new-server forms where no existing row should be excluded.
    """
    for row in await db_async.list_servers():
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
