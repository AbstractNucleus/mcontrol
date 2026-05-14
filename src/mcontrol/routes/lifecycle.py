"""HTMX-driven Start / Stop / Restart for a server.

Each handler hits the Docker API directly and updates state. RCON
password lifecycle is operator-managed in `server/server.properties`
(decision 024) — mcontrol no longer touches `.env` here.

The response shape (slice 13, decision 033) is a single HTML body
carrying two HTMX swap targets:

- The state pill, which arrives at `#state-pill` as `outerHTML` (the
  default swap declared on the buttons).
- The lifecycle-buttons wrapper, marked `hx-swap-oob="true"` so HTMX
  swaps it into place at `#lifecycle-buttons` alongside the primary
  swap. This keeps the three buttons' disabled / accent state in
  lock-step with the freshly-updated state.
"""

import asyncio
import socket
import time

import aiodocker
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from mcontrol import db, db_async, docker_client, lifecycle_state, server_rcon
from mcontrol.routes._dependencies import get_docker, get_server_or_404
from mcontrol.templates import templates

router = APIRouter()

_TIMEOUT_MSG = "Docker timed out — the container may still be starting. Try again."

# After docker_client.start() returns, the container process is up but
# the JVM may still be binding the listener port. Probe 127.0.0.1:port
# briefly so the DB state is honest: "running" only when the listener
# is up, otherwise "starting" (decision 041).
_LISTENER_PROBE_DEADLINE_S = 10.0
_LISTENER_PROBE_INTERVAL_S = 0.25
_LISTENER_PROBE_CONNECT_TIMEOUT_S = 0.5


async def _probe_listener(port: int) -> bool:
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


def _pill_and_buttons(server: dict, state: str, *, flash: str | None = None) -> HTMLResponse:
    pill = templates.get_template("_state_pill.html").render({"state": state})
    buttons = templates.get_template("_lifecycle_buttons.html").render(
        {
            "server": server,
            "state": state,
            "lifecycle": lifecycle_state.view(state),
            "oob": True,
        }
    )
    flash_html = templates.get_template("_lifecycle_flash.html").render(
        {"message": flash, "oob": True}
    )
    return HTMLResponse(pill + buttons + flash_html)


@router.post("/servers/{name}/lifecycle/start", response_class=HTMLResponse)
async def start(
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        await docker_client.start(docker, db.container_name_for(server))
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    # docker_client.start() returns when the container *process* is up,
    # not when the JVM has bound the listener. Probe 127.0.0.1:port and
    # only commit "running" once the port answers; otherwise commit
    # "starting" so the UI is honest (decision 041, issue #94).
    port = (server.get("variables") or {}).get("port")
    if isinstance(port, int):
        listening = await _probe_listener(port)
    else:
        listening = True
    new_state = "running" if listening else "starting"
    await db_async.update_server_state(name=name, state=new_state)
    return _pill_and_buttons(server, new_state)


@router.post("/servers/{name}/lifecycle/stop", response_class=HTMLResponse)
async def stop(
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        await docker_client.stop(docker, db.container_name_for(server))
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    await db_async.update_server_state(name=name, state="exited")
    server_rcon.forget_authed_password(name)
    return _pill_and_buttons(server, "exited")


@router.post("/servers/{name}/lifecycle/restart", response_class=HTMLResponse)
async def restart(
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        await docker_client.restart(docker, db.container_name_for(server))
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    await db_async.update_server_state(name=name, state="running")
    server_rcon.forget_authed_password(name)
    return _pill_and_buttons(server, "running")
