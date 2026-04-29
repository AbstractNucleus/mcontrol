"""Thin async wrapper around aiodocker for container-state lookups.

Slice 3 only needed to enumerate container names + statuses. Slice 4 will
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
            # Each container summary has _container (the raw dict from /containers/json).
            # 'Names' is a list of names with leading slash; pick the first.
            raw = c._container if hasattr(c, "_container") else {}
            names = raw.get("Names") or []
            if not names:
                continue
            name = names[0].lstrip("/")
            status = raw.get("State") or raw.get("Status", "unknown")
            states[name] = status
        return states
    except Exception:
        return {}
    finally:
        with suppress(Exception):
            await docker.close()
