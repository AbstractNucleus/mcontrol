"""SSE-streamed RCON console + POST endpoint for command submission.

Each server has at most one RCON connection, shared by every open SSE
stream for that server: a second tab, or a reload racing the previous
stream's teardown, simply subscribes to it. The first subscriber
attaches the mcontrol container to the MC's docker network and opens
the connection; the last one closes it. POST /servers/{name}/rcon
(form-encoded command=...) runs the command on the shared connection and
fans the echo + response out to every subscriber's stream.

While the server is unreachable (stopped, still booting, or the socket
dropped) the stream keeps retrying in the background and announces when
it connects, so a console opened before a start comes alive on its own.
Auth failures and docker errors are terminal.

The RCON password is read from `<dir>/server/server.properties`. If
`enable-rcon=false`, the line is empty, or the file is missing, the
stream yields a friendly info message and ends. lifecycle, logs, and
the rest of the panel stay working when RCON is disabled.

If no console is connected for a server, POST returns 409.
"""

import asyncio
import logging
import socket
from collections import defaultdict
from collections.abc import AsyncIterator, Coroutine
from contextlib import aclosing
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from markupsafe import escape

from mcontrol.domain import server_props
from mcontrol.infra import db, docker_client, rcon, server_rcon
from mcontrol.routes._dependencies import get_docker, get_server_or_404

router = APIRouter()
_log = logging.getLogger(__name__)

_RCON_PORT = 25575
_KEEPALIVE_S = 2.0
_RETRY_INTERVAL_S = 5.0
# Server name → live RconConnection shared by that server's subscribers.
_active_connections: dict[str, rcon._RconConnection] = {}
# Server name → one output queue per open SSE stream.
_subscribers: defaultdict[str, set[asyncio.Queue]] = defaultdict(set)
# Server name → Lock around opening/closing the shared connection.
_connection_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
# Server name → Lock serialising commands: concurrent submits on one
# RCON connection interleave protocol packets and desync it.
_submit_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
# Queue marker: the shared connection died, resubscribe.
_CONNECTION_LOST = object()
_teardown_tasks: set[asyncio.Task] = set()

_RCON_DISABLED_MSG = (
    "[info] RCON is not enabled for this server. Set "
    "enable-rcon=true and rcon.password=... in server/server.properties, "
    "then restart."
)
_AUTH_FAILED_MSG = (
    "[error] RCON authentication failed. Check rcon.password in "
    "server/server.properties (a changed password needs a server restart)."
)

# Terminal event: the pane's sse-close attribute shuts the EventSource down
# cleanly instead of auto-reconnecting and replaying the error forever.
_CLOSED = b"event: closed\ndata: \n\n"
_KEEPALIVE = b": keepalive\n\n"


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


def _unreachable_reason(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "connect timed out"
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused, server still starting?"
    if isinstance(exc, socket.gaierror):
        return "container hostname does not resolve, server stopped?"
    if isinstance(exc, rcon.RconClosedError):
        return "connection closed during auth"
    return str(exc) or exc.__class__.__name__


async def _subscribe(name: str, container_name: str, password: str) -> asyncio.Queue:
    """Register an output queue, opening the shared connection if needed."""
    async with _connection_locks[name]:
        conn = _active_connections.get(name)
        if conn is None or conn.closed:
            conn = await rcon.connect(container_name, _RCON_PORT, password)
            server_rcon.record_authed_password(name, password)
            _active_connections[name] = conn
        queue: asyncio.Queue = asyncio.Queue()
        _subscribers[name].add(queue)
        return queue


async def _unsubscribe(name: str, queue: asyncio.Queue) -> None:
    """Drop a queue; the last subscriber out closes the shared connection."""
    async with _connection_locks[name]:
        _subscribers[name].discard(queue)
        if _subscribers[name]:
            return
        conn = _active_connections.pop(name, None)
        if conn is not None:
            await conn.close()


def _broadcast(name: str, item: object) -> None:
    for queue in _subscribers[name]:
        queue.put_nowait(item)


async def _drop_connection(name: str, conn: rcon._RconConnection) -> None:
    """Forget a dead shared connection and tell its subscribers to reconnect."""
    await conn.close()
    if _active_connections.get(name) is conn:
        _active_connections.pop(name, None)
        _broadcast(name, _CONNECTION_LOST)


async def _shielded(coro: Coroutine) -> None:
    # A client disconnect reaches the generator as task cancellation that
    # anyio re-delivers on every await, which would cut cleanup I/O short.
    task = asyncio.ensure_future(coro)
    _teardown_tasks.add(task)
    task.add_done_callback(_teardown_tasks.discard)
    await asyncio.shield(task)


async def _detach_quietly(docker: aiodocker.Docker, network_name: str) -> None:
    try:
        await docker_client.detach_self_from_network(docker, network_name)
    except Exception:
        _log.warning("could not detach from %s", network_name, exc_info=True)


async def _wait_for_retry(request: Request) -> bool:
    """Sleep out the retry interval; True if the client left meanwhile."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _RETRY_INTERVAL_S
    while True:
        if await request.is_disconnected():
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(1.0, remaining))


async def _console(
    request: Request, name: str, container_name: str, props_path: Path
) -> AsyncIterator[bytes]:
    unreachable = False
    while True:
        enabled, password = _read_rcon_properties(props_path)
        if not enabled or not password:
            yield _message(_RCON_DISABLED_MSG)
            yield _CLOSED
            return
        try:
            queue = await _subscribe(name, container_name, password)
        except rcon.AuthenticationError:
            yield _message(_AUTH_FAILED_MSG)
            yield _CLOSED
            return
        except (OSError, rcon.RconClosedError) as exc:
            if unreachable:
                yield _KEEPALIVE
            else:
                unreachable = True
                yield _message(
                    f"[info] RCON unreachable ({_unreachable_reason(exc)}); "
                    "retrying while this page stays open"
                )
            if await _wait_for_retry(request):
                return
            continue
        except rcon.RconError as exc:
            yield _message(f"[error] RCON handshake failed: {exc}")
            yield _CLOSED
            return

        unreachable = False
        yield _message("[info] rcon connected")
        lost = False
        try:
            while not lost:
                if await request.is_disconnected():
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_S)
                except TimeoutError:
                    yield _KEEPALIVE
                    continue
                if item is _CONNECTION_LOST:
                    lost = True
                else:
                    yield _message(item)
        finally:
            await _shielded(_unsubscribe(name, queue))
        yield _message("[info] rcon connection lost; reconnecting")


async def _stream(
    request: Request,
    docker: aiodocker.Docker,
    name: str,
    container_name: str,
    server_dir: Path,
) -> AsyncIterator[bytes]:
    props_path = server_dir / "server" / "server.properties"
    enabled, password = _read_rcon_properties(props_path)
    if not enabled or not password:
        yield _message(_RCON_DISABLED_MSG)
        yield _CLOSED
        return

    try:
        network_name = await docker_client.find_network_name(docker, container_name)
        if network_name is None:
            yield _message("[error] no docker network found for container")
            yield _CLOSED
            return
        await docker_client.attach_self_to_network(docker, network_name)
    except aiodocker.DockerError as exc:
        yield _message(f"[error] docker: {exc.message}")
        yield _CLOSED
        return

    try:
        async with aclosing(_console(request, name, container_name, props_path)) as chunks:
            async for chunk in chunks:
                yield chunk
    finally:
        await _shielded(_detach_quietly(docker, network_name))


async def run_on_active(server_name: str, command: str) -> str | None:
    """Run ``command`` on the shared console RCON connection, if any.

    Whitelist/ops flips and the online chip reuse it so their commands
    show up in the console like typed ones. Returns ``None`` when no
    console is connected.
    """
    if server_name not in _active_connections:
        return None
    async with _submit_locks[server_name]:
        conn = _active_connections.get(server_name)
        if conn is None:
            return None
        _broadcast(server_name, f"> {command}")
        try:
            response = await conn.run(command)
        except (TimeoutError, rcon.RconError):
            # Timed-out or desynced sockets can't be reused: the streams
            # reconnect, later callers fall back to a one-shot client.
            await _drop_connection(server_name, conn)
            raise
        for line in (response or "").splitlines():
            _broadcast(server_name, line)
        return response


def console_owns_rcon(server_name: str) -> bool:
    """True while a detail-page SSE is opening or closing the shared connection."""
    return _connection_locks[server_name].locked()


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
            status_code=409,
            detail="RCON connection closed; the console is reconnecting, retry in a moment",
        ) from None
    except rcon.RconError as exc:
        raise HTTPException(
            status_code=502, detail=f"RCON protocol error: {exc}"
        ) from None
    if response is None:
        raise HTTPException(status_code=409, detail="RCON console is not connected")
    return HTMLResponse("", status_code=204)
