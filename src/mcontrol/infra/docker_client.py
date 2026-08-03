"""Thin async wrapper around aiodocker for the operations slice 4 needs:

- container_states_by_name(). discovery's existing read.
- start/stop/restart(name). lifecycle controls.
- logs_stream(name, tail). async generator of log lines for SSE.
- find_network_name(name). picks the MC container's docker network so
  mcontrol can attach to it for RCON.
- attach_self_to_network / detach_self_from_network. the network attach
  dance the RCON SSE wraps with.
- self_container_id(). used by the attach/detach calls.

Every entry point takes an ``aiodocker.Docker`` as its first argument.
The single long-lived client is opened in ``main.lifespan`` and stored on
``app.state.docker``; routes inject it via ``Depends(get_docker)`` and
pass it down to non-route callers (discovery, healthz, resources,
server_rcon). This replaces an earlier shape where each call opened and
closed its own client (~10 sites, see #98).
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import suppress

import aiodocker


def self_container_id() -> str:
    """Short docker container ID of the running mcontrol process.

    Docker sets HOSTNAME to the short container ID by default. If a
    deployment overrides hostname in compose, this assumption breaks -
    fall back to /etc/hostname.
    """
    hostname = os.environ.get("HOSTNAME")
    if hostname:
        return hostname
    with open("/etc/hostname") as f:
        return f.read().strip()


async def container_states_by_name(docker: aiodocker.Docker) -> dict[str, str]:
    """Return {container_name: status} for every container on the host.

    Returns an empty dict if the Docker daemon is unreachable. callers
    treat "no entry" as state="unknown" for that server.
    """
    try:
        containers = await docker.containers.list(all=True)
    except Exception:
        return {}
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


_LIFECYCLE_TIMEOUT_S = 30


async def start(docker: aiodocker.Docker, container_name: str) -> None:
    c = await docker.containers.get(container_name)
    await asyncio.wait_for(c.start(), timeout=_LIFECYCLE_TIMEOUT_S)


async def stop(docker: aiodocker.Docker, container_name: str) -> None:
    c = await docker.containers.get(container_name)
    await asyncio.wait_for(c.stop(), timeout=_LIFECYCLE_TIMEOUT_S)


async def restart(docker: aiodocker.Docker, container_name: str) -> None:
    c = await docker.containers.get(container_name)
    await asyncio.wait_for(c.restart(), timeout=_LIFECYCLE_TIMEOUT_S)


async def logs_stream(
    docker: aiodocker.Docker, container_name: str, *, tail: int = 200
) -> AsyncIterator[str]:
    """Async generator of log lines for a running container.

    Yields each line as a string (already decoded). Closes when the
    underlying aiodocker stream closes (caller disconnect, or container
    exit). Caller is responsible for catching cancellation.
    """
    c = await docker.containers.get(container_name)
    async for line in c.log(stdout=True, stderr=True, tail=tail, follow=True):
        yield line


async def find_network_name(
    docker: aiodocker.Docker, container_name: str
) -> str | None:
    """Return the name of the first non-host docker network the container
    is attached to, or None if it has none."""
    c = await docker.containers.get(container_name)
    info = await c.show()
    networks = info.get("NetworkSettings", {}).get("Networks", {}) or {}
    for name in networks:
        if name == "host":
            continue
        return name
    return None


# Concurrent holders (console SSE + one-shot RCON commands for the same
# server) share one network membership; without the refcount, one caller's
# finally-block detach yanks the network out from under the other's live
# RCON connection.
_network_refcounts: dict[str, int] = {}
_network_refcounts_lock = asyncio.Lock()


def _is_already_connected_error(exc: aiodocker.DockerError) -> bool:
    """Return whether Docker says this endpoint already exists in the network."""
    message = str(exc.message).lower()
    return (
        exc.status == 403
        and "endpoint with name " in message
        and " already exists in network " in message
    )


async def attach_self_to_network(
    docker: aiodocker.Docker, network_name: str
) -> None:
    """Connect the mcontrol container to the given docker network. Refcounted:
    only the 0→1 attach actually connects. An already-connected Docker response
    is treated as success."""
    async with _network_refcounts_lock:
        count = _network_refcounts.get(network_name, 0)
        if count == 0:
            network = await docker.networks.get(network_name)
            try:
                await network.connect({"Container": self_container_id()})
            except aiodocker.DockerError as exc:
                if not _is_already_connected_error(exc):
                    raise
        _network_refcounts[network_name] = count + 1


async def detach_self_from_network(
    docker: aiodocker.Docker, network_name: str
) -> None:
    """Refcounted counterpart: only the 1→0 detach actually disconnects.
    Floor at 0. an unpaired detach is a no-op."""
    async with _network_refcounts_lock:
        count = _network_refcounts.get(network_name, 0)
        if count > 1:
            _network_refcounts[network_name] = count - 1
            return
        _network_refcounts.pop(network_name, None)
        if count == 1:
            network = await docker.networks.get(network_name)
            with suppress(Exception):
                await network.disconnect({"Container": self_container_id()})
