"""Server-Sent Events endpoint streaming `docker logs --follow` for a
given server. Consumed by the log pane on the detail page (HTMX SSE
extension)."""

from collections.abc import AsyncIterator

import aiodocker
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from mcontrol.infra import db, docker_client
from mcontrol.routes._dependencies import get_docker, get_server_or_404

router = APIRouter()


async def _sse(docker: aiodocker.Docker, container_name: str) -> AsyncIterator[bytes]:
    async for line in docker_client.logs_stream(docker, container_name, tail=200):
        # Strip Docker's trailing newline (and any \r), defensively flatten
        # any *internal* newlines so they don't fracture the SSE event.
        text = line.rstrip("\r\n").replace("\r", "").replace("\n", " ")
        # Two "data:" lines per SSE event. the EventSource parser joins
        # them with \n, so the swap payload ends with a newline and each
        # log line lands on its own row in the <pre>. Single-data-line
        # payloads concatenate end-to-end under hx-swap="beforeend".
        yield f"data: {text}\ndata: \n\n".encode()


@router.get("/servers/{name}/logs")
async def stream(
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> StreamingResponse:
    container_name = db.container_name_for(server)
    return StreamingResponse(
        _sse(docker, container_name), media_type="text/event-stream"
    )
