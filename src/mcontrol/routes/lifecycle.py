"""HTMX-driven Start / Stop / Restart / Recreate for a server.

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

import logging

import aiodocker
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import lifecycle_state
from mcontrol.infra.compose import ComposeError
from mcontrol.routes._dependencies import get_docker, get_server_or_404
from mcontrol.services import lifecycle_service
from mcontrol.templates import templates

router = APIRouter()
logger = logging.getLogger(__name__)

_TIMEOUT_MSG = "Docker timed out; the container may still be starting. Try again."


def _docker_error_msg(exc: aiodocker.DockerError) -> str:
    raw = getattr(exc, "message", None)
    if isinstance(raw, dict):
        inner = raw.get("message")
        text = inner if isinstance(inner, str) and inner else None
    elif isinstance(raw, str) and raw:
        text = raw
    else:
        text = None
    if not text:
        text = str(exc)
    return f"Docker error: {text}. Check Bindings or run docker compose up."


def _action_failure(
    request: Request, server: dict, name: str, action: str, exc: BaseException
) -> HTMLResponse:
    logger.warning("lifecycle %s failed for %s: %s", action, name, exc)
    if isinstance(exc, ComposeError):
        flash = str(exc)
    elif isinstance(exc, aiodocker.DockerError):
        flash = _docker_error_msg(exc)
    else:
        flash = _TIMEOUT_MSG
    return _respond(request, server, server.get("state") or "unknown", flash=flash)


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


def _fleet_row(server: dict, state: str, *, flash: str | None = None) -> HTMLResponse:
    """Home-page quick-action response: the whole row re-renders with the
    new state (live stats arrive on the next page load, so memory/CPU show
    a dash). Errors toast into #flash-stack — the row has no flash slot."""
    row = {
        **server,
        "state": state,
        "port": (server.get("variables") or {}).get("port"),
    }
    html = templates.get_template("_fleet_row.html").render({"server": row})
    if flash:
        toast = templates.get_template("_flash.html").render(
            {"flash": {"kind": "error", "message": flash}}
        )
        html += f'<div hx-swap-oob="beforeend: #flash-stack">{toast}</div>'
    return HTMLResponse(html)


def _respond(
    request: Request, server: dict, state: str, *, flash: str | None = None
) -> HTMLResponse:
    if (request.headers.get("hx-target") or "").startswith("fleet-row-"):
        return _fleet_row(server, state, flash=flash)
    return _pill_and_buttons(server, state, flash=flash)


@router.post("/servers/{name}/lifecycle/start", response_class=HTMLResponse)
async def start(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        new_state = await lifecycle_service.start_server(docker, server, name)
    except (TimeoutError, ComposeError, aiodocker.DockerError) as exc:
        return _action_failure(request, server, name, "start", exc)
    return _respond(request, server, new_state)


@router.post("/servers/{name}/lifecycle/stop", response_class=HTMLResponse)
async def stop(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        new_state = await lifecycle_service.stop_server(docker, server, name)
    except (TimeoutError, ComposeError, aiodocker.DockerError) as exc:
        return _action_failure(request, server, name, "stop", exc)
    return _respond(request, server, new_state)


@router.post("/servers/{name}/lifecycle/restart", response_class=HTMLResponse)
async def restart(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        new_state = await lifecycle_service.restart_server(docker, server, name)
    except (TimeoutError, ComposeError, aiodocker.DockerError) as exc:
        return _action_failure(request, server, name, "restart", exc)
    return _respond(request, server, new_state)


@router.post("/servers/{name}/lifecycle/recreate", response_class=HTMLResponse)
async def recreate(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
) -> HTMLResponse:
    try:
        new_state = await lifecycle_service.recreate_server(server, name)
    except (TimeoutError, ComposeError, aiodocker.DockerError) as exc:
        return _action_failure(request, server, name, "recreate", exc)
    return _respond(request, server, new_state)
