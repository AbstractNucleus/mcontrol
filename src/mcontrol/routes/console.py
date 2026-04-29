"""SSE-streamed RCON console + POST endpoint for command submission.

Slice-4 model: one open SSE per server at a time. The route attaches
the mcontrol container to the MC's docker network on connect, opens an
RCON connection to <container_name>:25575, and streams server output
back as SSE `data:` messages. POST /servers/{name}/rcon (form-encoded
command=...) finds the live connection by server name and submits the
command; the response flows back through the SSE stream.

If no SSE is open for a server, POST returns 409 ("open the console
first").
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from mcontrol import db, docker_client, rcon

router = APIRouter()

_RCON_PORT = 25575
# Server name → live RconConnection, populated by SSE handler, cleared on disconnect.
_active_connections: dict[str, rcon._RconConnection] = {}
# Server name → asyncio.Queue[str] of output lines (responses from POST flow back here).
_output_queues: dict[str, asyncio.Queue] = {}


async def _stream(
    request: Request,
    name: str,
    container_name: str,
    password: str,
) -> AsyncIterator[bytes]:
    network_name = await docker_client.find_network_name(container_name)
    if network_name is None:
        yield b"data: [error] no docker network found for container\n\n"
        return

    await docker_client.attach_self_to_network(network_name)
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
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                yield f"data: {line}\n\n".encode("utf-8")
        finally:
            _active_connections.pop(name, None)
            _output_queues.pop(name, None)
            await conn.close()
    finally:
        await docker_client.detach_self_from_network(network_name)


@router.get("/servers/{name}/rcon")
async def stream(request: Request, name: str) -> StreamingResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    password = server.get("rcon_password")
    if not password:
        raise HTTPException(
            status_code=424,
            detail="rcon_password not yet set — start the server first to generate one",
        )

    container_name = db.container_name_for(server)
    return StreamingResponse(
        _stream(request, name, container_name, password),
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
