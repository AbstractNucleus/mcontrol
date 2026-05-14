"""Lifecycle service: start / stop / restart with post-start listener probe.

Decision 041: after ``docker_client.start()`` returns, probe
``127.0.0.1:port`` until either the connect succeeds (state="running")
or the deadline elapses (state="starting"). Stop and Restart commit a
flat state — the JVM-up-but-port-not-bound window only applies to start.

Routes call into here for the post-Docker state transition. The
"docker timed out" path raises ``TimeoutError`` straight through so
the route can render a flash; everything else returns the committed
state string.
"""

import asyncio
import socket
import time

import aiodocker

from mcontrol.infra import db, db_async, docker_client, server_rcon

# After docker_client.start() returns, the container process is up but
# the JVM may still be binding the listener port. Probe 127.0.0.1:port
# briefly so the DB state is honest: "running" only when the listener
# is up, otherwise "starting" (decision 041).
_LISTENER_PROBE_DEADLINE_S = 10.0
_LISTENER_PROBE_INTERVAL_S = 0.25
_LISTENER_PROBE_CONNECT_TIMEOUT_S = 0.5


async def probe_listener(port: int) -> bool:
    """Return True if a TCP connect to 127.0.0.1:port succeeds within
    the probe deadline. Connects are run in a thread to avoid blocking
    the event loop (decision 041)."""
    deadline = time.monotonic() + _LISTENER_PROBE_DEADLINE_S

    def _connect_once() -> bool:
        try:
            with socket.create_connection(
                ("127.0.0.1", port), timeout=_LISTENER_PROBE_CONNECT_TIMEOUT_S
            ):
                return True
        except OSError:
            return False

    while time.monotonic() < deadline:
        if await asyncio.to_thread(_connect_once):
            return True
        await asyncio.sleep(_LISTENER_PROBE_INTERVAL_S)
    return False


async def start_server(
    docker: aiodocker.Docker, server: dict, name: str
) -> str:
    """Start the container, probe the listener, commit + return new state.

    Returns ``"running"`` if the post-start TCP probe succeeds (or no
    port is known), ``"starting"`` if the probe times out. Propagates
    ``TimeoutError`` from ``docker_client.start`` so the route layer
    can show the timeout flash without updating state.
    """
    await docker_client.start(docker, db.container_name_for(server))
    port = (server.get("variables") or {}).get("port")
    if isinstance(port, int):
        listening = await probe_listener(port)
    else:
        listening = True
    new_state = "running" if listening else "starting"
    await db_async.update_server_state(name=name, state=new_state)
    return new_state


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
    """Restart the container, commit state=running, drop the cached RCON
    password baseline. Returns ``"running"`` on success."""
    await docker_client.restart(docker, db.container_name_for(server))
    await db_async.update_server_state(name=name, state="running")
    server_rcon.forget_authed_password(name)
    return "running"
