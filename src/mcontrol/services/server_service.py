"""Server-lifecycle service: scaffold, delete, migrate, update variables / bindings.

Routes here are the orchestration layer; this module owns the DB-first
ordering for scaffold, the tombstone rule for delete, the durable migration
file/DB handoff, and the JSONB merge for variables.
"""

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from mcontrol.domain import migration, scaffolding
from mcontrol.domain.scaffolding import DEFAULT_JAVA_VERSION
from mcontrol.infra import db, db_async

logger = logging.getLogger("mcontrol.services.server")


def _migration_committed(server: dict[str, Any] | None, variables: dict[str, Any]) -> bool:
    return bool(
        server is not None
        and server.get("scaffolded_at") is not None
        and server.get("variables") == variables
    )


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
    *, name: str, variables: dict[str, Any], server_dir: Path
) -> None:
    """Migrate files, then atomically stamp DB state with durable retry intent."""
    pending = migration.latest_recoverable_backup(server_dir)
    if pending is not None:
        intent = migration.read_migration_intent(server_dir, pending)
        if intent["files_ready"]:
            if (
                intent["name"] != name
                or migration.public_variables(intent["variables"])
                != migration.public_variables(variables)
            ):
                raise migration.MigrationError(
                    "An unfinished migration must resume using its saved values. Reload the "
                    "migration card and retry."
                )
            backup = pending
            variables = intent["variables"]
        else:
            migration.restore_backup(server_dir, pending)
            variables = migration.prepare_variables(name, variables, server_dir)
            backup = migration.migrate(name, variables, server_dir)
    else:
        variables = migration.prepare_variables(name, variables, server_dir)
        backup = migration.migrate(name, variables, server_dir)
    try:
        await db_async.complete_migration(name=name, variables=variables)
    except Exception as exc:
        try:
            observed = await db_async.get_server(name)
        except Exception:
            raise migration.MigrationError(
                "The database result could not be confirmed. Keep the server stopped; the "
                f"converted files and recovery backup {backup.name}/ were left in place."
            ) from exc
        if _migration_committed(observed, variables):
            migration.mark_backup_complete(server_dir, backup)
            return
        raise migration.MigrationError(
            "The database did not confirm the migration. Keep the server stopped; the converted "
            f"files and recovery backup {backup.name}/ were left ready for a safe retry."
        ) from exc
    try:
        observed = await db_async.get_server(name)
    except Exception as exc:
        raise migration.MigrationError(
            "Migration was sent to the database but could not be verified. Keep the server "
            f"stopped; recovery backup {backup.name}/ remains pending."
        ) from exc
    if not _migration_committed(observed, variables):
        raise migration.MigrationError(
            "The database did not accept this migration. Keep the server stopped; the converted "
            f"files and recovery backup {backup.name}/ were left ready for a safe retry."
        )
    try:
        migration.mark_backup_complete(server_dir, backup)
    except OSError as exc:
        raise migration.MigrationError(
            "Migration was saved, but its recovery marker could not be finalized. Keep the "
            "server stopped and retry after checking directory access."
        ) from exc


def ensure_no_pending_migration(server: dict[str, Any]) -> None:
    """Resolve a committed marker or block unsafe mutations after a crash."""
    server_dir = Path(server["dir"])
    pending = migration.latest_recoverable_backup(server_dir)
    if pending is None:
        return
    intent = migration.read_migration_intent(server_dir, pending)
    if (
        intent["files_ready"]
        and intent["name"] == server["name"]
        and _migration_committed(server, intent["variables"])
    ):
        migration.mark_backup_complete(server_dir, pending)
        return
    raise migration.MigrationError(
        "This server has an unfinished migration. Keep it stopped and retry migration before "
        "changing its managed setup."
    )


async def ensure_unique_container_identity(server: dict[str, Any]) -> None:
    """Refuse ambiguous lifecycle targeting when two rows name one container."""
    if not server.get("container_name"):
        return
    identity = db.container_name_for(server)
    for other in await db_async.list_servers():
        if other["name"] != server["name"] and db.container_name_for(other) == identity:
            raise migration.MigrationError(
                f"Bindings for {server['name']!r} and {other['name']!r} both target container "
                f"{identity!r}. Fix Bindings before starting or recreating it."
            )


async def update_server_variables(
    *, name: str, server: dict, new_values: dict[str, Any]
) -> dict[str, Any]:
    """Merge ``new_values`` into the existing JSONB and persist.

    Returns the merged dict so the route can re-render the card without
    a fresh DB round-trip. ``new_values`` must contain
    ``memory_budget_gb``, ``port``, ``server_jar``, ``java_version``,
    and an optional ``jvm_extra_args``: an empty/missing value drops
    the key from the merged JSONB (matches the slice 6 contract).
    """
    existing = server.get("variables") or {}
    updated = {
        **existing,
        "memory_budget_gb": new_values["memory_budget_gb"],
        "port": new_values["port"],
        "server_jar": new_values["server_jar"],
        "java_version": new_values.get("java_version", DEFAULT_JAVA_VERSION),
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
