"""SSE-streamed RCON console + POST endpoint for command submission.

One open SSE per server at a time. The route attaches the mcontrol
container to the MC's docker network on connect, opens an RCON
connection to <container_name>:25575, and streams server output back
as SSE `data:` messages. POST /servers/{name}/rcon (form-encoded
command=...) finds the live connection by server name and submits the
command; the response flows back through the SSE stream.

The RCON password is read from `<dir>/server/server.properties` at
SSE connect time. If `enable-rcon=false`, the line is
empty, or the file is missing, the stream yields a friendly info
message and ends. lifecycle, logs, and the rest of the panel stay
working when RCON is disabled.

If no SSE is open for a server, POST returns 409.
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from markupsafe import escape

from mcontrol.domain import server_props
from mcontrol.infra import db, docker_client, rcon, server_rcon
from mcontrol.routes._dependencies import get_docker, get_server_or_404

router = APIRouter()

_RCON_PORT = 25575
# Server name → live RconConnection, populated by SSE handler, cleared on disconnect.
_active_connections: dict[str, rcon._RconConnection] = {}
# Server name → asyncio.Queue[str] of output lines (responses from POST flow back here).
_output_queues: dict[str, asyncio.Queue] = {}
# Server name → Lock held for the entire lifetime of an open SSE stream.
# Prevents two concurrent clients from racing on _active_connections.
_connection_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
# Server name → Lock serialising POSTed commands: concurrent submits on one
# RCON connection interleave protocol packets and desync it.
_submit_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

_RCON_DISABLED_MSG = (
    "[info] RCON is not enabled for this server. Set "
    "enable-rcon=true and rcon.password=... in server/server.properties, "
    "then restart."
)

# Terminal event: the pane's sse-close attribute shuts the EventSource down
# cleanly instead of auto-reconnecting and replaying the error forever.
_CLOSED = b"event: closed\ndata: \n\n"


def _payload(line: str) -> str:
    """HTML-escaped, classified console line (the client swaps HTML)."""
    if line.startswith("> "):
        css = "console-line console-line--cmd"
    elif line.startswith("[error]"):
        css = "console-line console-line--error"
    elif line.startswith("[info]"):
        css = "console-line console-line--dim"
    else:
        css = "console-line"
    return f'<span class="{css}">{escape(line)}</span>'


def _message(line: str) -> bytes:
    # Two "data:" lines: the joined payload ends with \n so each line lands
    # on its own row under hx-swap="beforeend" (same trick as logs.py).
    return f"data: {_payload(line)}\ndata: \n\n".encode()


def _read_rcon_properties(props_path: Path) -> tuple[bool, str]:
    """Return (enabled, password) parsed from a server.properties file.

    `enabled` is True iff `enable-rcon=true`. `password` is the
    `rcon.password=` value, or "" if absent. Missing file → (False, "").
    """
    props = server_props.read_properties(props_path)
    enabled = props.get("enable-rcon", "").lower() == "true"
    password = props.get("rcon.password", "")
    return enabled, password


async def _stream(
    request: Request,
    docker: aiodocker.Docker,
    name: str,
    container_name: str,
    server_dir: Path,
) -> AsyncIterator[bytes]:
    enabled, password = _read_rcon_properties(server_dir / "server" / "server.properties")
    if not enabled or not password:
        yield _message(_RCON_DISABLED_MSG)
        yield _CLOSED
        return

    lock = _connection_locks[name]
    if lock.locked():
        yield _message("[error] console already open in another tab")
        yield _CLOSED
        return
    await lock.acquire()
    try:
        network_name = await docker_client.find_network_name(docker, container_name)
        if network_name is None:
            yield _message("[error] no docker network found for container")
            yield _CLOSED
            return

        await docker_client.attach_self_to_network(docker, network_name)
        try:
            conn = await rcon.connect(container_name, _RCON_PORT, password)
            server_rcon.record_authed_password(name, password)
            queue: asyncio.Queue = asyncio.Queue()
            _active_connections[name] = conn
            _output_queues[name] = queue

            try:
                yield _message("[info] rcon connected")
                # Poll for client disconnect alongside queue reads. Short timeout
                # keeps the loop responsive when the SSE consumer goes away.
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        line = await asyncio.wait_for(queue.get(), timeout=2.0)
                    except TimeoutError:
                        yield b": keepalive\n\n"
                        continue
                    yield _message(line)
            finally:
                _active_connections.pop(name, None)
                _output_queues.pop(name, None)
                await conn.close()
        finally:
            await docker_client.detach_self_from_network(docker, network_name)
    finally:
        lock.release()


async def run_on_active(server_name: str, command: str) -> str | None:
    """Run ``command`` on the live console RCON connection, if any.

    Minecraft RCON typically allows only one client. Whitelist/ops flips
    and the online chip must reuse this connection when the detail page
    already holds it, otherwise a second connect races the SSE and can
    EOF mid-command. Returns ``None`` when no console is open.
    """
    if server_name not in _active_connections:
        return None
    async with _submit_locks[server_name]:
        if server_name not in _active_connections:
            return None
        conn = _active_connections[server_name]
        queue = _output_queues.get(server_name)
        response = await conn.run(command)
        if queue is not None:
            await queue.put(f"> {command}")
            for line in (response or "").splitlines():
                await queue.put(line)
        return response


@router.get("/servers/{name}/rcon")
async def stream(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> StreamingResponse:
    return StreamingResponse(
        _stream(
            request,
            docker,
            name,
            db.container_name_for(server),
            Path(server["dir"]),
        ),
        media_type="text/event-stream",
    )


@router.post("/servers/{name}/rcon", response_class=HTMLResponse)
async def submit(name: str, command: str = Form(...)) -> HTMLResponse:
    try:
        response = await run_on_active(name, command)
    except TimeoutError:
        raise HTTPException(
            status_code=504, detail="RCON command timed out"
        ) from None
    except rcon.RconClosedError:
        raise HTTPException(
            status_code=409, detail="RCON connection closed; reopen the console"
        ) from None
    if response is None:
        raise HTTPException(status_code=409, detail="open the console first")
    return HTMLResponse("", status_code=204)
