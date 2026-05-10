import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, db, resources
from mcontrol.templates import templates

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
