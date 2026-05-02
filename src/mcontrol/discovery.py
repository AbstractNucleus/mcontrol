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

from mcontrol import db, docker_client


async def run_discovery(base_path: Path) -> int:
    """Walk base_path, insert new rows, refresh state on existing rows.

    Returns the count of dirs seen. If base_path doesn't exist, returns
    0 without touching the DB. If Docker is unreachable, every dir
    gets state="unknown" via the empty mapping returned from
    docker_client.
    """
    if not base_path.exists():
        return 0

    states = await docker_client.container_states_by_name()
    count = 0
    for entry in sorted(base_path.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue

        existing = db.get_server(entry.name)
        if existing is None:
            db.insert_server(
                name=entry.name,
                dir=str(entry),
                state=states.get(entry.name, "unknown"),
            )
        else:
            # Use the row's container_name override when looking up state —
            # the actual docker container may be named differently from the
            # directory once an operator has repointed it.
            container_name = db.container_name_for(existing)
            db.update_server_state(
                name=entry.name,
                state=states.get(container_name, "unknown"),
            )
        count += 1
    return count
