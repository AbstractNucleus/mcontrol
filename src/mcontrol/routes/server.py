from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, health, lifecycle_state
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.templates import templates

router = APIRouter()


@router.get("/servers/{name}", response_class=HTMLResponse)
async def server_detail(
    request: Request, server: dict = Depends(get_server_or_404)
) -> HTMLResponse:
    state = server.get("state", "unknown")
    return templates.TemplateResponse(
        request=request,
        name="server_detail.html",
        context={
            "version": __version__,
            "server": server,
            "state": state,
            "lifecycle": lifecycle_state.view(state),
            "health_issues": health.compute_issues(server),
            "scripts_stale": health.compute_scripts_stale(server),
        },
    )
