"""Server-Sent Events endpoint streaming `docker logs --follow` for a
given server. Consumed by streams.js through a dedicated EventSource.

Payload contract: each event's data is an HTML-escaped, level-classified
<span> (the client swaps it into the <pre> as HTML, so raw log text must
never pass through unescaped — player chat legitimately contains ``<``).
Events carry ``id:`` so a reconnecting EventSource presents
``Last-Event-ID`` and the route can skip the backlog tail instead of
replaying it. Terminal conditions emit ``event: closed`` which the pane's
client turns into a clean EventSource shutdown rather
than an infinite reconnect-and-replay loop.
"""

import re
from collections.abc import AsyncIterator

import aiodocker
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from markupsafe import escape

from mcontrol.infra import db, docker_client
from mcontrol.routes._dependencies import get_docker, get_server_or_404

router = APIRouter()

_LEVEL_RE = re.compile(r"\[(?:[^\]]*/)?(INFO|WARN|ERROR|FATAL|DEBUG)\]")
_LEVEL_CLASS = {
    "WARN": "log-line--warn",
    "ERROR": "log-line--error",
    "FATAL": "log-line--error",
    "DEBUG": "log-line--dim",
}


def render_line(text: str, *, base: str = "log-line") -> str:
    match = _LEVEL_RE.search(text)
    level_class = _LEVEL_CLASS.get(match.group(1)) if match else None
    css = f"{base} {level_class}" if level_class else base
    return f'<span class="{css}">{escape(text)}</span>'


def _message(text: str, event_id: int) -> bytes:
    # Retain the trailing newline in the SSE payload. The current client
    # renders each classified span as a separate row.
    return f"id: {event_id}\ndata: {render_line(text)}\ndata: \n\n".encode()


_CLOSED = b"event: closed\ndata: \n\n"


async def _sse(
    docker: aiodocker.Docker, container_name: str, *, skip_tail: bool
) -> AsyncIterator[bytes]:
    event_id = 0
    try:
        async for line in docker_client.logs_stream(
            docker, container_name, tail=0 if skip_tail else 200
        ):
            # Docker can deliver several log lines in one frame. Emit each
            # separately so SSE framing and per-line severity stay intact.
            lines = line.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if lines[-1] == "":
                lines.pop()  # A trailing terminator does not add an extra row.
            for text in lines:
                event_id += 1
                yield _message(text, event_id)
    except aiodocker.DockerError:
        yield _message("[info] container not found", event_id + 1)
        yield _CLOSED
        return
    # `docker logs --follow` ends when the container stops.
    yield _message("[info] log stream ended", event_id + 1)
    yield _CLOSED


@router.get("/servers/{name}/logs")
async def stream(
    request: Request,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> StreamingResponse:
    container_name = db.container_name_for(server)
    skip_tail = (
        request.headers.get("last-event-id") is not None
        or request.query_params.get("resume") == "1"
    )
    return StreamingResponse(
        _sse(docker, container_name, skip_tail=skip_tail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
