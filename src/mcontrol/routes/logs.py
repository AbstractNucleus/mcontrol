"""Server-Sent Events endpoint streaming `docker logs --follow` for a
given server. Consumed by the log pane on the detail page (HTMX SSE
extension)."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from mcontrol import db, docker_client

router = APIRouter()


async def _sse(container_name: str) -> AsyncIterator[bytes]:
    async for line in docker_client.logs_stream(container_name, tail=200):
        # Each line becomes one SSE message. \n inside a line would split
        # the SSE payload, so flatten any internal newlines.
        flat = line.replace("\r", "").replace("\n", " ")
        yield f"data: {flat}\n\n".encode()


@router.get("/servers/{name}/logs")
async def stream(name: str) -> StreamingResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    container_name = db.container_name_for(server)
    return StreamingResponse(_sse(container_name), media_type="text/event-stream")
