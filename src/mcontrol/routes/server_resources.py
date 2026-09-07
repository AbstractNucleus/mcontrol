import asyncio
from datetime import UTC, datetime
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import lifecycle_state
from mcontrol.infra import db, db_async, resources
from mcontrol.routes._dependencies import get_docker, get_server_or_404
from mcontrol.services import telemetry
from mcontrol.templates import templates

router = APIRouter()

_CAPTION_BY_STATUS = {
    "not-running": "container not running",
    "unreachable": "Docker daemon unreachable",
    "missing": "container not found",
}


_reconcile_state = telemetry.observed_state


@router.get("/servers/{name}/resources", response_class=HTMLResponse)
async def get_card(
    request: Request,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    container_name = db.container_name_for(server)
    stats = await resources.read_container_stats(docker, container_name)
    context: dict = {
        "request": request,
        "server": server,
        "updated_at": datetime.now(UTC).isoformat(),
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

    if stats["status"] == "unreachable":
        raise HTTPException(
            status_code=503, detail="Docker daemon unreachable. Last values may be stale."
        )
    body = templates.get_template("_resources_card.html").render(context)

    new_state = await _reconcile_state(server, stats)
    if new_state:
        await db_async.update_server_state(name=server["name"], state=new_state)
        body += templates.get_template("_state_pill.html").render({"state": new_state, "oob": True})
        body += templates.get_template("_lifecycle_buttons.html").render(
            {
                "server": server,
                "state": new_state,
                "lifecycle": lifecycle_state.view(new_state),
                "oob": True,
            }
        )
    return HTMLResponse(body)


@router.get("/servers/{name}/disk", response_class=HTMLResponse)
async def get_disk(request: Request, server: dict = Depends(get_server_or_404)) -> HTMLResponse:
    # Keep an in-flight walk shared after a request times out; retries must not
    # create another worker for the same potentially large directory.
    jobs = getattr(request.app.state, "disk_jobs", None)
    if jobs is None:
        jobs = request.app.state.disk_jobs = {}
    path = Path(server["dir"])
    task = jobs.get(path)
    if task is None:
        task = asyncio.create_task(asyncio.to_thread(resources.read_disk_usage, path))
        jobs[path] = task
    try:
        disk_bytes = await asyncio.wait_for(asyncio.shield(task), 10)
    except TimeoutError:
        raise HTTPException(
            status_code=503, detail="Disk measurement is taking longer than expected."
        ) from None
    finally:
        if task.done():
            jobs.pop(path, None)
    return templates.TemplateResponse(
        request=request,
        name="_disk_status.html",
        context={"server": server, "disk_human": resources.format_bytes(disk_bytes)},
    )
