"""Thin async wrapper around aiodocker for container-state lookups.

Slice 3 only needs to enumerate container names + statuses. Slice 4 will
extend this module with start/stop/logs operations.
"""

from contextlib import suppress

import aiodocker

from mcontrol.settings import Settings


async def container_states_by_name() -> dict[str, str]:
    """Return {container_name: status} for every container on the host.

    Returns an empty dict if the Docker daemon is unreachable — callers
    treat "no entry" as state="unknown" for that server.
    """
    settings = Settings()
    try:
        docker = aiodocker.Docker(url=settings.docker_host)
    except Exception:
        return {}

    try:
        containers = await docker.containers.list(all=True)
        states: dict[str, str] = {}
        for c in containers:
            info = await c.show()
            name = info["Name"].lstrip("/")
            states[name] = info["State"]["Status"]
        return states
    except Exception:
        return {}
    finally:
        with suppress(Exception):
            await docker.close()
