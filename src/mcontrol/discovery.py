"""Server discovery — walks SERVER_BASE_PATH and registers each subdirectory
in app_mcontrol.servers, refreshing its state from Docker.

Idempotent. Designed to run once on app startup via FastAPI's lifespan
context manager. A future slice may add a "Rescan" button.
"""

from pathlib import Path

from mcontrol import db, docker_client


async def run_discovery(base_path: Path) -> int:
    """Walk base_path, upsert each subdirectory. Returns count of dirs seen.

    If base_path doesn't exist, returns 0 without touching the DB. If Docker
    is unreachable, every dir gets state="unknown" via the empty mapping
    returned from docker_client.
    """
    if not base_path.exists():
        return 0

    states = await docker_client.container_states_by_name()
    count = 0
    for entry in sorted(base_path.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        db.upsert_server(
            name=entry.name,
            dir=str(entry),
            state=states.get(entry.name, "unknown"),
        )
        count += 1
    return count
