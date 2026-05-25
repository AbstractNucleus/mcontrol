"""Server-lifecycle service: scaffold, delete, migrate, update variables / bindings.

Routes here are the orchestration layer; this module owns the DB-first
ordering for scaffold, the tombstone rule for delete, the
migration → variables-write → mark-scaffolded sequence, and the
JSONB merge for variables.
"""

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from mcontrol.domain import migration, scaffolding
from mcontrol.infra import db_async

logger = logging.getLogger("mcontrol.services.server")


class ScaffoldError(Exception):
    """A new-server scaffold failed mid-flight and rollback ran.

    Carries an operator-facing ``detail`` that may include an orphan path
    when rollback's ``rmtree`` itself failed (issue #93). The route layer
    maps this to ``HTTPException(500, detail=...)``.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def scaffold_new_server(
    *,
    name: str,
    target: Path,
    variables: dict[str, Any],
    loader: str,
    base: Path,
) -> None:
    """Insert row → render+write files → mark scaffolded; rollback on failure.

    ``target`` is ``base / name`` resolved. The path-safety check happens
    at the call site (route layer) because it's a 422 surface, not a 500.
    On any failure between the insert and the mark, best-effort rollback
    runs (rmtree the directory, delete the DB row) and raises
    :class:`ScaffoldError` for the route to map to a 500.
    """
    await db_async.insert_scaffolding_server(
        name=name, dir=str(target), variables=variables, loader=loader
    )
    try:
        scaffolding.scaffold(name, variables, base)
        await db_async.mark_scaffolded(name=name)
    except Exception:
        logger.exception("scaffold failed for %r. rolling back", name)
        orphan: Path | None = None
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError:
                logger.exception(
                    "rollback rmtree failed for %r at %s. operator must remove manually",
                    name,
                    target,
                )
                orphan = target
        try:
            await db_async.delete_server(name)
        except Exception:
            logger.exception("rollback delete_server failed for %r", name)
        detail = "failed to scaffold server"
        if orphan is not None:
            detail += f"; orphan directory left at {orphan}"
        raise ScaffoldError(detail) from None


async def delete_server_with_tombstone(server: dict, base: Path) -> None:
    """Rename ``<server.dir>`` to ``<base>/.deleted-<name>-<ts>/`` and delete row.

    Idempotent on a missing directory. the DB row is still removed so
    a hand-deleted dir converges. State-check (refuses ``running``) is
    the route layer's job because it's a 409 surface.
    """
    name = server["name"]
    server_dir = Path(server["dir"]).resolve()
    tomb_path = base / f".deleted-{name}-{int(time.time())}"

    if server_dir.exists():
        server_dir.rename(tomb_path)

    await db_async.delete_server(name)


async def migrate_legacy_server(
    *, name: str, variables: dict[str, Any], base: Path
) -> None:
    """Run the legacy-to-scaffold migration + stamp the row.

    Order: file ops first (``migration.migrate`` is idempotent), then
    ``update_variables``, then ``mark_scaffolded``. State and
    scaffolded-at checks happen in the route layer.
    """
    migration.migrate(name, variables, base)
    await db_async.update_variables(name=name, variables=variables)
    await db_async.mark_scaffolded(name=name)


async def update_server_variables(
    *, name: str, server: dict, new_values: dict[str, Any]
) -> dict[str, Any]:
    """Merge ``new_values`` into the existing JSONB and persist.

    Returns the merged dict so the route can re-render the card without
    a fresh DB round-trip. ``new_values`` must contain
    ``memory_budget_gb``, ``port``, ``server_jar``, and an optional
    ``jvm_extra_args``: an empty/missing value drops the key from the
    merged JSONB (matches the slice 6 contract).
    """
    existing = server.get("variables") or {}
    updated = {
        **existing,
        "memory_budget_gb": new_values["memory_budget_gb"],
        "port": new_values["port"],
        "server_jar": new_values["server_jar"],
    }
    if new_values.get("jvm_extra_args"):
        updated["jvm_extra_args"] = new_values["jvm_extra_args"]
    else:
        updated.pop("jvm_extra_args", None)

    await db_async.update_variables(name=name, variables=updated)
    return updated


async def update_server_bindings(
    *, name: str, container_name: str | None, dir: str
) -> None:
    """Persist the per-server ``container_name`` override and ``dir``."""
    await db_async.update_bindings(name=name, container_name=container_name, dir=dir)
