"""Delete-server flow with type-name confirm + tombstone.

  GET  /servers/{name}/delete   → confirm partial (type-name input)
  POST /servers/{name}/delete   → re-checks state, tombstones <dir>,
                                  deletes the row, returns HX-Redirect /

The Delete action (detail header ⋯ menu) is disabled when state='running'.
The POST endpoint re-checks state at request time (returns 409) so a
race where the operator starts the server in another tab between
page render and confirm-click still refuses cleanly. The tombstone +
DB delete sequence lives in ``services.server_service``.
"""

import logging
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import lifecycle_state, migration
from mcontrol.infra import db, docker_client
from mcontrol.routes._dependencies import (
    get_docker,
    get_locked_server_or_404,
    get_server_or_404,
)
from mcontrol.routes._flash import hx_redirect
from mcontrol.services import server_service
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()
logger = logging.getLogger(__name__)


def _partial(
    request: Request,
    server: dict,
    *,
    error: str | None = None,
    typed: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_delete_confirm.html",
        context={
            "server": server,
            "error": error,
            "typed": typed,
        },
        status_code=status_code,
    )


@router.get("/servers/{name}/delete", response_class=HTMLResponse)
async def get(
    request: Request,
    server: dict = Depends(get_server_or_404),
) -> HTMLResponse:
    return _partial(request, server)


@router.post("/servers/{name}/delete", response_class=HTMLResponse)
async def post(
    request: Request,
    name: str,
    server: dict = Depends(get_locked_server_or_404),
    confirm_name: str = Form(""),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    try:
        server_service.ensure_no_pending_migration(server)
    except migration.MigrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # The DB state column can be stale (started outside the panel), so
    # also ask Docker before tombstoning a bind-mount the JVM may still
    # be writing to. An unreachable daemon yields {} and the DB check
    # stands alone. A reachable daemon that has no container for this
    # name (removed out of band) must not 409 on a stale "running" row.
    container_name = db.container_name_for(server)
    live_states = await docker_client.container_states_by_name(docker)
    container_absent = bool(live_states) and container_name not in live_states
    if lifecycle_state.is_running(server) and not container_absent:
        raise HTTPException(
            status_code=409, detail="Stop the server before deleting."
        )
    if live_states.get(container_name) == "running":
        raise HTTPException(
            status_code=409, detail="Stop the server before deleting."
        )

    if confirm_name.strip() != name:
        return _partial(
            request,
            server,
            error=f"Type the server name ({name!r}) exactly to confirm.",
            typed=confirm_name,
            status_code=422,
        )

    settings: Settings = request.app.state.settings
    base = Path(settings.server_base_path).resolve()

    await server_service.delete_server_with_tombstone(server, base)

    try:
        await docker_client.remove_container(docker, container_name)
    except Exception:
        logger.warning("failed to remove container %s after delete", container_name, exc_info=True)

    # HTMX picks up HX-Redirect and navigates to /. The confirm modal's
    # #server-modal slot was the form's swap target; without the
    # redirect we'd swap an empty body into it. The cookie flash lands
    # in #flash-stack on Home.
    return hx_redirect("/", kind="ok", message=f"Deleted {name} (moved to Trash).")
