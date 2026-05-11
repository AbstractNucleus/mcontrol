import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from mcontrol import __version__, db, discovery, resources
from mcontrol.settings import Settings
from mcontrol.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_memory(stats: object) -> str | None:
    """Render the home cell from a read_container_stats result.

    Returns a string when the container is running, None otherwise.
    Slice 9 resolution #12: derive caption from live stats, not the
    DB state column — both not-running and daemon-unreachable collapse
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


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    servers = db.list_servers()

    container_names = [db.container_name_for(row) for row in servers]
    stats_results = await asyncio.gather(
        *(resources.read_container_stats(name) for name in container_names),
        return_exceptions=True,
    )

    rows = [
        {**row, "memory": _format_memory(stats)}
        for row, stats in zip(servers, stats_results, strict=True)
    ]

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"version": __version__, "servers": rows},
    )


@router.post("/rescan")
async def rescan(request: Request) -> Response:
    """Operator-triggered discovery (decision 034).

    Re-runs the same idempotent `discovery.run_discovery` routine the
    lifespan kicks off at startup (decision 021). On HTMX requests
    returns 204 + `HX-Refresh: true` so the client reloads `/` and
    picks up the freshly-discovered rows. On plain-HTTP requests
    (curl, no-JS), returns 303 → `/`.

    A missing `SERVER_BASE_PATH` directory surfaces as 503; this is the
    operator's signal that the deployment-level bind mount has dropped
    out (the lifespan handler logs and continues at startup — same
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

    count = await discovery.run_discovery(base_path)
    logger.info("rescan: %d server dir(s) seen under %s", count, base_path)

    if request.headers.get("hx-request"):
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return RedirectResponse(url="/", status_code=303)
