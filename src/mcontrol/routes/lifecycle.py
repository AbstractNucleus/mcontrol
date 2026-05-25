"""HTMX-driven Start / Stop / Restart for a server.

Each handler delegates to ``services.lifecycle_service`` for the
Docker + DB + RCON-password-cache side; the route is responsible for
HTMX response shape, the post-action OOB swap, and the timeout flash.

The response shape is a single HTML body
carrying two HTMX swap targets:

- The state pill, which arrives at `#state-pill` as `outerHTML` (the
  default swap declared on the buttons).
- The lifecycle-buttons wrapper, marked `hx-swap-oob="true"` so HTMX
  swaps it into place at `#lifecycle-buttons` alongside the primary
  swap. This keeps the three buttons' disabled / accent state in
  lock-step with the freshly-updated state.
"""

import aiodocker
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from mcontrol.domain import lifecycle_state
from mcontrol.routes._dependencies import get_docker, get_server_or_404
from mcontrol.services import lifecycle_service
from mcontrol.templates import templates

router = APIRouter()

_TIMEOUT_MSG = "Docker timed out; the container may still be starting. Try again."


def _pill_and_buttons(server: dict, state: str, *, flash: str | None = None) -> HTMLResponse:
    pill = templates.get_template("_state_pill.html").render({"state": state})
    buttons = templates.get_template("_lifecycle_buttons.html").render(
        {
            "server": server,
            "state": state,
            "lifecycle": lifecycle_state.view(state),
            "oob": True,
        }
    )
    flash_html = templates.get_template("_lifecycle_flash.html").render(
        {"message": flash, "oob": True}
    )
    return HTMLResponse(pill + buttons + flash_html)


@router.post("/servers/{name}/lifecycle/start", response_class=HTMLResponse)
async def start(
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        new_state = await lifecycle_service.start_server(docker, server, name)
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    return _pill_and_buttons(server, new_state)


@router.post("/servers/{name}/lifecycle/stop", response_class=HTMLResponse)
async def stop(
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        new_state = await lifecycle_service.stop_server(docker, server, name)
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    return _pill_and_buttons(server, new_state)


@router.post("/servers/{name}/lifecycle/restart", response_class=HTMLResponse)
async def restart(
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        new_state = await lifecycle_service.restart_server(docker, server, name)
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    return _pill_and_buttons(server, new_state)
