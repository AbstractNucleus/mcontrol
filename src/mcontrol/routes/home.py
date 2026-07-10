import asyncio
import logging
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from mcontrol.domain import discovery
from mcontrol.infra import db, db_async, resources
from mcontrol.routes._dependencies import get_docker
from mcontrol.settings import Settings
from mcontrol.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_memory(stats: object) -> str | None:
    """Render the home cell from a read_container_stats result.

    Returns a string when the container is running, None otherwise.
    Slice 9 resolution #12: derive caption from live stats, not the
    DB state column. both not-running and daemon-unreachable collapse
    to a single dash on the home surface.
    """
    if not isinstance(stats, dict) or stats.get("status") != "ok":
        return None
    mem_used = stats["mem_used"]
    mem_limit = stats["mem_limit"]
    mem_percent = (mem_used / mem_limit * 100.0) if mem_limit else 0.0
    return (
        f"{resources.format_bytes(mem_used)} / "
        f"{resources.format_bytes(mem_limit)} "
        f"({mem_percent:.0f} %)"
    )


def _row_view(row: dict, stats: object) -> dict:
    ok = isinstance(stats, dict) and stats.get("status") == "ok"
    return {
        **row,
        "memory": _format_memory(stats),
        "cpu": f"{stats['cpu_percent']:.1f} %" if ok else None,
        "mem_used": stats["mem_used"] if ok else 0,
        "mem_limit": stats["mem_limit"] if ok else 0,
        "started_at": stats.get("started_at") if ok else None,
        "port": (row.get("variables") or {}).get("port"),
    }


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    servers = await db_async.list_servers()

    container_names = [db.container_name_for(row) for row in servers]
    stats_results = await asyncio.gather(
        *(
            resources.read_container_stats(docker, name)
            for name in container_names
        ),
        return_exceptions=True,
    )

    rows = [
        _row_view(row, stats)
        for row, stats in zip(servers, stats_results, strict=True)
    ]

    mem_limit = sum(r["mem_limit"] for r in rows)
    summary = {
        "total": len(rows),
        "running": sum(1 for r in rows if r.get("state") == "running"),
        "memory": (
            f"{resources.format_bytes(sum(r['mem_used'] for r in rows))}"
            f" / {resources.format_bytes(mem_limit)}"
            if mem_limit
            else None
        ),
    }

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"servers": rows, "summary": summary},
    )


@router.post("/rescan")
async def rescan(
    request: Request,
    docker: aiodocker.Docker = Depends(get_docker),
) -> Response:
    """Operator-triggered discovery.

    Re-runs the same idempotent `discovery.run_discovery` routine the
    lifespan kicks off at startup. On HTMX requests
    returns 204 + `HX-Refresh: true` so the client reloads `/` and
    picks up the freshly-discovered rows. On plain-HTTP requests
    (curl, no-JS), returns 303 → `/`.

    A missing `SERVER_BASE_PATH` directory surfaces as 503; this is the
    operator's signal that the deployment-level bind mount has dropped
    out (the lifespan handler logs and continues at startup. same
    surface from the operator-trigger side would silently hide the
    problem).
    """
    settings: Settings = request.app.state.settings
    base_path = Path(settings.server_base_path)
    if not base_path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"server_base_path does not exist: {base_path}",
        )

    count = await discovery.run_discovery(docker, base_path)
    logger.info("rescan: %d server dir(s) seen under %s", count, base_path)

    if request.headers.get("hx-request"):
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return RedirectResponse(url="/", status_code=303)
