"""Shared form validator for the server-variables field set.

Used by routes/new_server.py, routes/migrate.py, and routes/variables.py,
all of which accept the same (memory_budget_gb, port, server_jar,
java_version, jvm_extra_args) fields with the same rules.
"""

import socket
from pathlib import Path
from typing import Literal

from mcontrol.domain import migration
from mcontrol.domain.scaffolding import (
    DEFAULT_JAVA_VERSION,
    HEADROOM_GB,
    JAVA_VERSIONS,
    MEMORY_MIN_GB,
)
from mcontrol.infra import db_async

PORT_MIN = 1024
PORT_MAX = 65535
_PORT_PROBE_TIMEOUT = 0.5

# `/servers/new` is the create form; a server with that name would be
# unreachable behind it.
RESERVED_NAMES: frozenset[str] = frozenset({"new"})

# Loader enum, mirroring app_mcontrol.servers.loader in supabase-server.
# Order is significant for `infer_loader_from_jar`: forge → fabric →
# paper → quilt → vanilla, first match wins. Vanilla is the fallback
# and never matches by name (no jar filename contains "vanilla" reliably).
LOADERS: tuple[str, ...] = ("vanilla", "forge", "fabric", "paper", "quilt")
Loader = Literal["vanilla", "forge", "fabric", "paper", "quilt"]
_INFER_ORDER: tuple[str, ...] = ("forge", "fabric", "paper", "quilt")


def infer_loader_from_jar(server_jar: str) -> Loader:
    """Best-effort guess of the loader from the jar filename.

    Case-insensitive substring match in `forge → fabric → paper → quilt`
    order, vanilla as the fallback. New-server form submissions do NOT
    call this; the operator's dropdown choice is authoritative there.
    Kept here so future callers (legacy-row backfill, migrate flow) share
    one rule.
    """
    needle = server_jar.lower()
    for loader in _INFER_ORDER:
        if loader in needle:
            return loader  # type: ignore[return-value]
    return "vanilla"


def validate(form: dict) -> dict[str, str]:
    """Validate the variables fields. No DB or disk lookups."""
    errors: dict[str, str] = {}
    if form["memory_budget_gb"] - HEADROOM_GB < 1:
        errors["memory_budget_gb"] = (
            f"Minimum {MEMORY_MIN_GB} GB ({HEADROOM_GB} GB headroom + at least 1 GB heap)."
        )
    if not (PORT_MIN <= form["port"] <= PORT_MAX):
        errors["port"] = f"Port must be between {PORT_MIN} and {PORT_MAX}."
    if not form["server_jar"].strip():
        errors["server_jar"] = "Required."
    if "loader" in form and form["loader"] not in LOADERS:
        errors["loader"] = f"Must be one of: {', '.join(LOADERS)}."
    if "java_version" in form and form["java_version"] not in JAVA_VERSIONS:
        errors["java_version"] = (
            f"Must be one of: {', '.join(str(v) for v in JAVA_VERSIONS)}."
        )
    return errors


def build_variables(form: dict) -> dict:
    """Assemble the variables JSONB from a validated form dict.

    ``jvm_extra_args`` is omitted when empty so the stored shape stays
    minimal and the start-script template's ``.get(..., "")`` default
    applies. Shared by the new-server and migrate flows; the variables
    *edit* flow merges into existing JSONB instead (see
    ``server_service.update_server_variables``).
    """
    variables: dict = {
        "memory_budget_gb": form["memory_budget_gb"],
        "port": form["port"],
        "server_jar": form["server_jar"],
        "java_version": form.get("java_version", DEFAULT_JAVA_VERSION),
    }
    if form.get("jvm_extra_args"):
        variables["jvm_extra_args"] = form["jvm_extra_args"]
    return variables


def _row_port(row: dict) -> tuple[int | None, str]:
    """(host port, source) for a server row. Scaffolded rows carry it in
    variables; legacy rows only have it in their docker-compose.yml."""
    row_vars = row.get("variables") or {}
    if "port" in row_vars:
        return row_vars["port"], "variables"
    if row.get("dir"):
        return migration.parse_compose_port(Path(row["dir"])), "docker-compose.yml"
    return None, ""


async def check_port_collision(exclude_name: str | None, port: int) -> str | None:
    """Return an error string if *port* is already used by another server.

    Pass *exclude_name* as the current server's name so a server can keep
    its own port without triggering a false collision. Pass ``None`` for
    new-server forms where no existing row should be excluded.
    """
    for row in await db_async.list_servers():
        if exclude_name is not None and row["name"] == exclude_name:
            continue
        row_port, source = _row_port(row)
        if row_port == port:
            suffix = " (from its docker-compose.yml)" if source == "docker-compose.yml" else ""
            return f"Port {port} is already used by '{row['name']}'{suffix}."
    return None


def check_port_bound(port: int, host: str = "127.0.0.1") -> str | None:
    """Return an error string if something at *host* is already listening
    on *port*. Catches collisions with non-mcontrol services that
    ``check_port_collision`` can't see (issue #124). Blocking; callers
    on the event loop run it via ``asyncio.to_thread``.
    """
    try:
        with socket.create_connection((host, port), timeout=_PORT_PROBE_TIMEOUT):
            return f"Port {port} is already bound on this host."
    except OSError:
        return None
