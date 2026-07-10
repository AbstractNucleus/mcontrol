"""Per-server Resources card (slice 9 PR 1).

Single endpoint:

  GET /servers/{name}/resources  → renders _resources_card.html

The card auto-polls every 5s via HTMX (`hx-trigger="load, every 5s"`),
swapping itself in place. Polling stops automatically when the
operator navigates away. the trigger lives on a DOM node that the
detail page replaces on navigation.

The poll doubles as the state reconciler: the DB state column only
changes when a lifecycle button writes it, so a crash (or a "starting"
that finished) would lie on the pill forever. When the live container
state diverges, the route commits the live state and appends OOB
re-renders of the pill + lifecycle buttons to the card response.
Steady-state responses stay byte-identical (no OOB fragments, no
flicker). "unreachable" never reconciles — daemon blips must not churn
state.

Container resolution goes through ``db.container_name_for(row)`` so a
re-pointed row reads the right container. Disk usage
roots at the row's ``dir``; the plan's path-safety
contract relies on ``dir`` being DB-sourced, not URL-sourced.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import lifecycle_state
from mcontrol.infra import db, db_async, resources
from mcontrol.routes._dependencies import get_docker, get_server_or_404
from mcontrol.services import lifecycle_service
from mcontrol.templates import templates

router = APIRouter()

_CAPTION_BY_STATUS = {
    "not-running": "container not running",
    "unreachable": "Docker daemon unreachable",
}


async def _reconcile_state(server: dict, stats: dict) -> str | None:
    """Live state to commit, or None when the DB is already honest.

    Promotion to "running" waits for the listener port to accept: Docker
    reports "running" during the port-unbound window (the start handler
    mid-probe — when the DB still holds the pre-start state — or an
    out-of-band start), and committing early would stomp the start
    handler's honest "starting".
    """
    live = stats.get("container_state")
    if not live:
        return None
    db_state = server.get("state")
    if live == db_state:
        return None
    if live == "running":
        port = (server.get("variables") or {}).get("port")
        if isinstance(port, int) and not await lifecycle_service.probe_listener_once(
            port
        ):
            return None
        return "running"
    return live


@router.get("/servers/{name}/resources", response_class=HTMLResponse)
async def get_card(
    request: Request,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    container_name = db.container_name_for(server)
    stats = await resources.read_container_stats(docker, container_name)
    # Full-tree walk; keep it off the event loop.
    disk_bytes = await asyncio.to_thread(
        resources.read_disk_usage, Path(server["dir"])
    )

    context: dict = {
        "request": request,
        "server": server,
        "disk_bytes": disk_bytes,
        "disk_human": resources.format_bytes(disk_bytes),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "format_bytes": resources.format_bytes,
    }
    if stats["status"] == "ok":
        mem_used = stats["mem_used"]
        mem_limit = stats["mem_limit"]
        mem_percent = (mem_used / mem_limit * 100.0) if mem_limit else 0.0
        context.update(
            {
                "ok": True,
                "caption": None,
                "cpu_percent": stats["cpu_percent"],
                "mem_used": mem_used,
                "mem_limit": mem_limit,
                "mem_percent": mem_percent,
                "started_at": stats.get("started_at"),
            }
        )
    else:
        context.update(
            {
                "ok": False,
                "caption": _CAPTION_BY_STATUS.get(stats["status"], stats["status"]),
                "started_at": None,
            }
        )

    body = templates.get_template("_resources_card.html").render(context)

    new_state = await _reconcile_state(server, stats)
    if new_state:
        await db_async.update_server_state(name=server["name"], state=new_state)
        body += templates.get_template("_state_pill.html").render(
            {"state": new_state, "oob": True}
        )
        body += templates.get_template("_lifecycle_buttons.html").render(
            {
                "server": server,
                "state": new_state,
                "lifecycle": lifecycle_state.view(new_state),
                "oob": True,
            }
        )
    return HTMLResponse(body)
