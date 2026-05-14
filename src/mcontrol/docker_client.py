"""Thin async wrapper around aiodocker for the operations slice 4 needs:

- container_states_by_name() — discovery's existing read.
- start/stop/restart(name) — lifecycle controls.
- logs_stream(name, tail) — async generator of log lines for SSE.
- find_network_name(name) — picks the MC container's docker network so
  mcontrol can attach to it for RCON.
- attach_self_to_network / detach_self_from_network — the network attach
  dance the RCON SSE wraps with.
- self_container_id() — used by the attach/detach calls.
"""

import os
from collections.abc import AsyncIterator
from contextlib import suppress

import aiodocker

from mcontrol.settings import get_settings


def self_container_id() -> str:
    """Short docker container ID of the running mcontrol process.

    Docker sets HOSTNAME to the short container ID by default. If a
    deployment overrides hostname in compose, this assumption breaks —
    fall back to /etc/hostname.
    """
    hostname = os.environ.get("HOSTNAME")
    if hostname:
        return hostname
    with open("/etc/hostname") as f:
        return f.read().strip()


async def container_states_by_name() -> dict[str, str]:
    """Return {container_name: status} for every container on the host.

    Returns an empty dict if the Docker daemon is unreachable — callers
    treat "no entry" as state="unknown" for that server.
    """
    settings = get_settings()
    try:
        docker = aiodocker.Docker(url=settings.docker_host)
    except Exception:
        return {}

    try:
        containers = await docker.containers.list(all=True)
        states: dict[str, str] = {}
        for c in containers:
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


async def start(container_name: str) -> None:
    docker = aiodocker.Docker(url=get_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        await c.start()
    finally:
        with suppress(Exception):
            await docker.close()


async def stop(container_name: str) -> None:
    docker = aiodocker.Docker(url=get_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        await c.stop()
    finally:
        with suppress(Exception):
            await docker.close()


async def restart(container_name: str) -> None:
    docker = aiodocker.Docker(url=get_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        await c.restart()
    finally:
        with suppress(Exception):
            await docker.close()


async def logs_stream(
    container_name: str, *, tail: int = 200
) -> AsyncIterator[str]:
    """Async generator of log lines for a running container.

    Yields each line as a string (already decoded). Closes when the
    underlying aiodocker stream closes (caller disconnect, or container
    exit). Caller is responsible for catching cancellation.
    """
    docker = aiodocker.Docker(url=get_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        async for line in c.log(stdout=True, stderr=True, tail=tail, follow=True):
            yield line
    finally:
        with suppress(Exception):
            await docker.close()


async def find_network_name(container_name: str) -> str | None:
    """Return the name of the first non-host docker network the container
    is attached to, or None if it has none."""
    docker = aiodocker.Docker(url=get_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        info = await c.show()
        networks = info.get("NetworkSettings", {}).get("Networks", {}) or {}
        for name in networks:
            if name == "host":
                continue
            return name
        return None
    finally:
        with suppress(Exception):
            await docker.close()


async def attach_self_to_network(network_name: str) -> None:
    """Connect the mcontrol container to the given docker network. Idempotent
    in practice: if already connected, the API returns 403 which we suppress."""
    docker = aiodocker.Docker(url=get_settings().docker_host)
    try:
        network = await docker.networks.get(network_name)
        with suppress(Exception):
            await network.connect(container=self_container_id())
    finally:
        with suppress(Exception):
            await docker.close()


async def detach_self_from_network(network_name: str) -> None:
    docker = aiodocker.Docker(url=get_settings().docker_host)
    try:
        network = await docker.networks.get(network_name)
        with suppress(Exception):
            await network.disconnect(container=self_container_id())
    finally:
        with suppress(Exception):
            await docker.close()
