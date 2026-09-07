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
from collections import defaultdict
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
# Per-network: serialise connect/disconnect of *this* container so a hung
# attach cannot hold the global refcount lock and stall every other server.
_network_attach_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
# Connecting *this* container to a server network via the mounted docker.sock
# can stall well past aiohttp's client timeout (the daemon is mutating our
# own netns). Bound it so SSE can retry / error instead of holding Send.
# asyncio.wait_for() on the HTTP call is not enough: cancelling aiodocker
# waits until the request actually dies (often sock_read=30s), so we shield
# the connect and let it finish in the background after 8s.
_ATTACH_TIMEOUT_S = 8.0
# EventSource retries ~3s after a drop. Immediate 1→0 disconnect would
# NetworkDisconnect + NetworkConnect on every retry, mutating our netns
# and killing the new SSE TCP connection. Stay joined for a cooldown.
_DETACH_COOLDOWN_S = 30.0
_inflight_connects: dict[str, asyncio.Task] = {}
_pending_detaches: dict[str, asyncio.Task] = {}


def _is_already_connected_error(exc: aiodocker.DockerError) -> bool:
    """Return whether Docker says this endpoint already exists in the network."""
    message = str(exc.message).lower()
    return (
        exc.status == 403
        and "endpoint with name " in message
        and " already exists in network " in message
    )


async def _already_on_network(
    docker: aiodocker.Docker, network_name: str
) -> bool:
    """True if inspect shows this container already joined ``network_name``."""
    try:
        info = await _self_inspect(docker)
    except Exception:
        return False
    if not info:
        return False
    networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
    return network_name in networks


def _cancel_pending_detach(network_name: str) -> None:
    task = _pending_detaches.pop(network_name, None)
    if task is not None and not task.done():
        task.cancel()


def _on_connect_done(network_name: str, task: asyncio.Task) -> None:
    if _inflight_connects.get(network_name) is task:
        _inflight_connects.pop(network_name, None)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("background attach to %s failed: %s", network_name, exc)


async def _connect_endpoint(docker: aiodocker.Docker, network_name: str) -> None:
    network = await docker.networks.get(network_name)
    try:
        await network.connect({"Container": self_container_id()})
    except aiodocker.DockerError as exc:
        if not _is_already_connected_error(exc):
            raise


def _bump_refcount(network_name: str) -> None:
    _network_refcounts[network_name] = _network_refcounts.get(network_name, 0) + 1


async def attach_self_to_network(
    docker: aiodocker.Docker, network_name: str
) -> None:
    """Connect the mcontrol container to the given docker network. Refcounted:
    only the 0→1 attach actually connects. Already-connected (inspect or a
    403 from Docker) is success. A hung ``NetworkConnect`` times out in 8s
    even if the Docker HTTP call ignores cancellation."""
    async with _network_attach_locks[network_name]:
        _cancel_pending_detach(network_name)
        async with _network_refcounts_lock:
            count = _network_refcounts.get(network_name, 0)
            if count > 0:
                _network_refcounts[network_name] = count + 1
                return
        inflight = _inflight_connects.get(network_name)
        if inflight is None or inflight.done():
            if await _already_on_network(docker, network_name):
                async with _network_refcounts_lock:
                    _bump_refcount(network_name)
                return
            inflight = asyncio.create_task(
                _connect_endpoint(docker, network_name)
            )
            _inflight_connects[network_name] = inflight
            inflight.add_done_callback(
                lambda t, n=network_name: _on_connect_done(n, t)
            )
        try:
            await asyncio.wait_for(
                asyncio.shield(inflight), timeout=_ATTACH_TIMEOUT_S
            )
        except TimeoutError:
            # Shield keeps the HTTP call running; cancelling it often lets
            # dockerd finish anyway. Inspect before treating this as failure.
            if await _already_on_network(docker, network_name):
                logger.info(
                    "attach to %s timed out but endpoint is present",
                    network_name,
                )
            else:
                logger.warning("timed out attaching to %s", network_name)
                raise
        except aiodocker.DockerError as exc:
            if not _is_already_connected_error(exc):
                raise
        async with _network_refcounts_lock:
            _bump_refcount(network_name)


async def _disconnect_after_cooldown(
    docker: aiodocker.Docker, network_name: str
) -> None:
    try:
        await asyncio.sleep(_DETACH_COOLDOWN_S)
        async with _network_attach_locks[network_name]:
            async with _network_refcounts_lock:
                if _network_refcounts.get(network_name, 0) > 0:
                    return
            network = await docker.networks.get(network_name)
            with suppress(Exception):
                await network.disconnect({"Container": self_container_id()})
    except asyncio.CancelledError:
        raise
    finally:
        if _pending_detaches.get(network_name) is asyncio.current_task():
            _pending_detaches.pop(network_name, None)


async def detach_self_from_network(
    docker: aiodocker.Docker, network_name: str
) -> None:
    """Refcounted counterpart: only the 1→0 detach actually disconnects.
    Floor at 0. an unpaired detach is a no-op. The real NetworkDisconnect
    is delayed so a reconnecting EventSource can skip-if-already-connected
    instead of flapping our netns."""
    async with _network_attach_locks[network_name]:
        async with _network_refcounts_lock:
            count = _network_refcounts.get(network_name, 0)
            if count > 1:
                _network_refcounts[network_name] = count - 1
                return
            _network_refcounts.pop(network_name, None)
            should_disconnect = count == 1
        if not should_disconnect:
            return
        if _DETACH_COOLDOWN_S <= 0:
            network = await docker.networks.get(network_name)
            with suppress(Exception):
                await network.disconnect({"Container": self_container_id()})
            return
        _cancel_pending_detach(network_name)
        task = asyncio.create_task(
            _disconnect_after_cooldown(docker, network_name)
        )
        _pending_detaches[network_name] = task


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
    for task in list(_pending_detaches.values()):
        if not task.done():
            task.cancel()
    _pending_detaches.clear()
    for task in list(_inflight_connects.values()):
        if not task.done():
            task.cancel()
    _inflight_connects.clear()
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
