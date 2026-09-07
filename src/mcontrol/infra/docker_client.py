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
import logging
import os
from collections.abc import AsyncIterator
from contextlib import suppress

import aiodocker

logger = logging.getLogger(__name__)

_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"


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


async def _self_inspect(docker: aiodocker.Docker) -> dict | None:
    """``docker inspect`` of this process's own container; None when not
    running inside Docker (no such container, or no hostname file)."""
    try:
        cid = self_container_id()
    except OSError:
        return None
    try:
        return await (await docker.containers.get(cid)).show()
    except aiodocker.DockerError as exc:
        if exc.status == 404:
            return None
        raise


async def self_network_gateway(docker: aiodocker.Docker) -> str | None:
    """Gateway IP of the first Docker network this container is attached
    to. Host-published ports are reachable through it from inside the
    container. None when not running in Docker or no gateway is known."""
    info = await _self_inspect(docker)
    if info is None:
        return None
    networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
    for endpoint in networks.values():
        gateway = (endpoint or {}).get("Gateway")
        if gateway:
            return gateway
    return None


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
_STOP_GRACE_S = 90
_STOP_WAIT_S = _STOP_GRACE_S + 10


async def start(docker: aiodocker.Docker, container_name: str) -> None:
    c = await docker.containers.get(container_name)
    await asyncio.wait_for(c.start(), timeout=_LIFECYCLE_TIMEOUT_S)


async def stop(docker: aiodocker.Docker, container_name: str) -> None:
    c = await docker.containers.get(container_name)
    await asyncio.wait_for(c.stop(t=_STOP_GRACE_S), timeout=_STOP_WAIT_S)


async def restart(docker: aiodocker.Docker, container_name: str) -> None:
    c = await docker.containers.get(container_name)
    await asyncio.wait_for(c.restart(), timeout=_LIFECYCLE_TIMEOUT_S)


async def remove_container(docker: aiodocker.Docker, container_name: str) -> None:
    """Remove a stopped container. Missing (404) is a no-op."""
    try:
        c = await docker.containers.get(container_name)
        await c.delete(v=False)
    except aiodocker.DockerError as exc:
        if exc.status == 404:
            return
        raise


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


def _keep_self_network(name: str, info: dict) -> bool:
    """Networks we must stay on: the one we were started with, our
    compose project, and Docker builtins. Everything else is a leaked
    RCON attachment to a server network."""
    if name in {"bridge", "host", "none", "ingress"}:
        return True
    host_mode = (info.get("HostConfig") or {}).get("NetworkMode") or ""
    if name == host_mode:
        return True
    labels = (info.get("Config") or {}).get("Labels") or {}
    project = labels.get(_COMPOSE_PROJECT_LABEL)
    if project and (name == project or name.startswith(f"{project}_")):
        return True
    if name == "mcontrol_default" or name.startswith("mcontrol_"):
        return True
    return False


async def prune_stale_self_networks(docker: aiodocker.Docker) -> None:
    """Disconnect leftover server-network attachments. No-op off Docker."""
    try:
        info = await _self_inspect(docker)
    except Exception:
        logger.warning("could not inspect self for network prune", exc_info=True)
        return
    if info is None:
        return
    try:
        cid = self_container_id()
    except OSError:
        return
    networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
    for name in networks:
        if _keep_self_network(name, info):
            continue
        try:
            network = await docker.networks.get(name)
            await network.disconnect({"Container": cid})
            logger.info("disconnected stale network attachment %s", name)
        except Exception:
            logger.warning("failed to disconnect stale network %s", name, exc_info=True)


async def disconnect_refcount_networks(docker: aiodocker.Docker) -> None:
    """Best-effort detach of every network still in ``_network_refcounts``."""
    async with _network_refcounts_lock:
        names = list(_network_refcounts)
        _network_refcounts.clear()
    if not names:
        return
    try:
        cid = self_container_id()
    except OSError:
        return
    for name in names:
        try:
            network = await docker.networks.get(name)
            await network.disconnect({"Container": cid})
        except Exception:
            logger.warning("failed to disconnect %s on shutdown", name, exc_info=True)
