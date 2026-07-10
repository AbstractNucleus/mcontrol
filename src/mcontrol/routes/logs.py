"""Server-Sent Events endpoint streaming `docker logs --follow` for a
given server. Consumed by the log pane on the detail page (HTMX SSE
extension).

Payload contract: each event's data is an HTML-escaped, level-classified
<span> (the client swaps it into the <pre> as HTML, so raw log text must
never pass through unescaped — player chat legitimately contains ``<``).
Events carry ``id:`` so a reconnecting EventSource presents
``Last-Event-ID`` and the route can skip the backlog tail instead of
replaying it. Terminal conditions emit ``event: closed`` which the pane's
``sse-close`` attribute turns into a clean EventSource shutdown rather
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
    # Two "data:" lines per SSE event. the EventSource parser joins
    # them with \n, so the swap payload ends with a newline and each
    # log line lands on its own row in the <pre>. Single-data-line
    # payloads concatenate end-to-end under hx-swap="beforeend".
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
            # Strip Docker's trailing newline (and any \r), defensively flatten
            # any *internal* newlines so they don't fracture the SSE event.
            text = line.rstrip("\r\n").replace("\r", "").replace("\n", " ")
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
    skip_tail = request.headers.get("last-event-id") is not None
    return StreamingResponse(
        _sse(docker, container_name, skip_tail=skip_tail),
        media_type="text/event-stream",
    )
