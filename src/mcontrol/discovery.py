"""Server discovery — walks SERVER_BASE_PATH and registers each
subdirectory in app_mcontrol.servers, refreshing its state from Docker.

Design (decision 021): this routine is idempotent and **non-destructive
of operator edits**. On a re-scan, dir and container_name (which the
operator may have edited) are NEVER overwritten — only `state` is
refreshed. New directories are inserted with default values; existing
rows are touched only on the `state` column.

Designed to run once on app startup via FastAPI's lifespan context
manager.
"""

from pathlib import Path

import aiodocker

from mcontrol import db, db_async, docker_client


async def run_discovery(docker: aiodocker.Docker, base_path: Path) -> int:
    """Walk base_path, insert new rows, refresh state on existing rows.

    Returns the count of dirs seen. If base_path doesn't exist, returns
    0 without touching the DB. If Docker is unreachable, every dir
    gets state="unknown" via the empty mapping returned from
    docker_client.
    """
    if not base_path.exists():
        return 0

    states = await docker_client.container_states_by_name(docker)
    count = 0
    for entry in sorted(base_path.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        # Decision 026: skip dot-prefixed dirs so tombstoned dirs don't
        # resurrect on the next scan. Same filter handles .git,
        # lost+found, and any other operator-introduced non-server dir.
        if entry.name.startswith("."):
            continue

        existing = await db_async.get_server(entry.name)
        if existing is None:
            await db_async.insert_server(
                name=entry.name,
                dir=str(entry),
                state=states.get(entry.name, "unknown"),
            )
        else:
            # Use the row's container_name override when looking up state —
            # the actual docker container may be named differently from the
            # directory once an operator has repointed it.
            container_name = db.container_name_for(existing)
            await db_async.update_server_state(
                name=entry.name,
                state=states.get(container_name, "unknown"),
            )
        count += 1
    return count
