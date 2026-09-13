"""Lifecycle service: start / stop / restart / recreate with listener probe.

After Docker reports the container is up, probe ``probe_host():port``
until the connect succeeds (state="running") or the deadline elapses
(state="starting"). Start, restart, and recreate share that probe;
stop commits ``exited``.

``probe_host`` is re-exported from ``infra.probe_host`` so batch D's
``getattr(lifecycle_service, "probe_host")`` and
``from mcontrol.services.lifecycle_service import probe_host`` both work.

Routes call into here for the post-Docker state transition. The
"docker timed out" path raises ``TimeoutError`` straight through so
the route can render a flash; everything else returns the committed
state string.
"""

import asyncio
import socket
import time
from pathlib import Path

import aiodocker

from mcontrol.infra import compose, db, db_async, docker_client, server_rcon
from mcontrol.infra.probe_host import probe_host
from mcontrol.services import server_service

# After docker_client.start() returns, the container process is up but
# the JVM may still be binding the listener port. Probe probe_host:port
# briefly so the DB state is honest: "running" only when the listener
# is up, otherwise "starting".
_LISTENER_PROBE_DEADLINE_S = 10.0
_LISTENER_PROBE_INTERVAL_S = 0.25
_LISTENER_PROBE_CONNECT_TIMEOUT_S = 0.5


def _connect_once(port: int) -> bool:
    try:
        with socket.create_connection(
            (probe_host(), port), timeout=_LISTENER_PROBE_CONNECT_TIMEOUT_S
        ):
            return True
    except OSError:
        return False


async def probe_listener(port: int) -> bool:
    """Return True if a TCP connect to probe_host:port succeeds within
    the probe deadline. Connects are run in a thread to avoid blocking
    the event loop."""
    deadline = time.monotonic() + _LISTENER_PROBE_DEADLINE_S

    while time.monotonic() < deadline:
        if await asyncio.to_thread(_connect_once, port):
            return True
        await asyncio.sleep(_LISTENER_PROBE_INTERVAL_S)
    return False


async def probe_listener_once(port: int) -> bool:
    """Single-shot probe for the resources-poll reconciler; the deadline
    probe above would stall the 5s card refresh."""
    return await asyncio.to_thread(_connect_once, port)


async def _commit_listener_state(server: dict, name: str) -> str:
    port = (server.get("variables") or {}).get("port")
    if isinstance(port, int):
        listening = await probe_listener(port)
    else:
        listening = True
    new_state = "running" if listening else "starting"
    await db_async.update_server_state(name=name, state=new_state)
    return new_state


async def start_server(
    docker: aiodocker.Docker, server: dict, name: str
) -> str:
    """Start the container, probe the listener, commit + return new state.

    When the container does not exist (aiodocker 404) and the server
    dir has a compose file, run ``docker compose up -d`` first.

    Returns ``"running"`` if the post-start TCP probe succeeds (or no
    port is known), ``"starting"`` if the probe times out. Propagates
    ``TimeoutError`` from ``docker_client.start`` so the route layer
    can show the timeout flash without updating state.
    """
    server_service.ensure_no_pending_migration(server)
    await server_service.ensure_unique_container_identity(server)
    try:
        await docker_client.start(docker, db.container_name_for(server))
    except aiodocker.DockerError as exc:
        if exc.status != 404:
            raise
        server_dir = Path(server["dir"])
        if not (server_dir / "docker-compose.yml").is_file():
            raise
        await compose.compose_up(server_dir)
    return await _commit_listener_state(server, name)


async def stop_server(
    docker: aiodocker.Docker, server: dict, name: str
) -> str:
    """Stop the container, commit state=exited, drop the cached RCON
    password baseline. Returns ``"exited"`` on success."""
    await docker_client.stop(docker, db.container_name_for(server))
    await db_async.update_server_state(name=name, state="exited")
    server_rcon.forget_authed_password(name)
    return "exited"


async def restart_server(
    docker: aiodocker.Docker, server: dict, name: str
) -> str:
    """Restart the container, probe the listener, commit starting/running,
    drop the cached RCON password baseline."""
    server_service.ensure_no_pending_migration(server)
    await server_service.ensure_unique_container_identity(server)
    await docker_client.restart(docker, db.container_name_for(server))
    server_rcon.forget_authed_password(name)
    return await _commit_listener_state(server, name)


async def recreate_server(server: dict, name: str) -> str:
    """``docker compose up -d`` (recreates only when config changed), then
    probe the listener and commit starting/running."""
    server_service.ensure_no_pending_migration(server)
    await server_service.ensure_unique_container_identity(server)
    await compose.compose_up(Path(server["dir"]))
    server_rcon.forget_authed_password(name)
    return await _commit_listener_state(server, name)
