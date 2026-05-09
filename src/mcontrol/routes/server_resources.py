"""Per-server Resources card (slice 9 PR 1).

Single endpoint:

  GET /servers/{name}/resources  → renders _resources_card.html

The card auto-polls every 5s via HTMX (`hx-trigger="load, every 5s"`),
swapping itself in place. Polling stops automatically when the
operator navigates away — the trigger lives on a DOM node that the
detail page replaces on navigation.

Container resolution goes through ``db.container_name_for(row)`` so a
re-pointed row reads the right container (decision 021). Disk usage
roots at the row's ``dir`` (decision 008); the plan's path-safety
contract relies on ``dir`` being DB-sourced, not URL-sourced.
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import db, resources
from mcontrol.templates import templates

router = APIRouter()

_CAPTION_BY_STATUS = {
    "not-running": "container not running",
    "unreachable": "Docker daemon unreachable",
}


@router.get("/servers/{name}/resources", response_class=HTMLResponse)
async def get_card(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    container_name = db.container_name_for(server)
    stats = await resources.read_container_stats(container_name)
    disk_bytes = resources.read_disk_usage(Path(server["dir"]))

    context: dict = {
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
            }
        )
    else:
        context.update(
            {
                "ok": False,
                "caption": _CAPTION_BY_STATUS.get(stats["status"], stats["status"]),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="_resources_card.html",
        context=context,
    )
