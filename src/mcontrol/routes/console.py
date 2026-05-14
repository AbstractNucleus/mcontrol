"""SSE-streamed RCON console + POST endpoint for command submission.

One open SSE per server at a time. The route attaches the mcontrol
container to the MC's docker network on connect, opens an RCON
connection to <container_name>:25575, and streams server output back
as SSE `data:` messages. POST /servers/{name}/rcon (form-encoded
command=...) finds the live connection by server name and submits the
command; the response flows back through the SSE stream.

The RCON password is read from `<dir>/server/server.properties` at
SSE connect time (decision 024). If `enable-rcon=false`, the line is
empty, or the file is missing, the stream yields a friendly info
message and ends — lifecycle, logs, and the rest of the panel stay
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

from mcontrol import db, docker_client, rcon, server_props
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

_RCON_DISABLED_MSG = (
    b"data: [info] RCON is not enabled for this server. Set "
    b"enable-rcon=true and rcon.password=... in server/server.properties, "
    b"then restart.\n\n"
)


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
        yield _RCON_DISABLED_MSG
        return

    lock = _connection_locks[name]
    if lock.locked():
        yield b"data: [error] console already open in another tab\n\n"
        return
    await lock.acquire()
    try:
        network_name = await docker_client.find_network_name(docker, container_name)
        if network_name is None:
            yield b"data: [error] no docker network found for container\n\n"
            return

        await docker_client.attach_self_to_network(docker, network_name)
        try:
            conn = await rcon.connect(container_name, _RCON_PORT, password)
            queue: asyncio.Queue = asyncio.Queue()
            _active_connections[name] = conn
            _output_queues[name] = queue

            try:
                yield b"data: [info] rcon connected\n\n"
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
                    yield f"data: {line}\n\n".encode()
            finally:
                _active_connections.pop(name, None)
                _output_queues.pop(name, None)
                await conn.close()
        finally:
            await docker_client.detach_self_from_network(docker, network_name)
    finally:
        lock.release()


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
    if name not in _active_connections:
        raise HTTPException(status_code=409, detail="open the console first")
    conn = _active_connections[name]
    queue = _output_queues[name]
    response = await conn.run(command)
    # Echo the command + response into the SSE stream.
    await queue.put(f"> {command}")
    if response:
        await queue.put(response)
    return HTMLResponse("", status_code=204)
