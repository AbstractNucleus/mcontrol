"""HTMX-driven Start / Stop / Restart for a server.

Each handler hits the Docker API directly and updates state. RCON
password lifecycle is operator-managed in `server/server.properties`
(decision 024) — mcontrol no longer touches `.env` here.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import db, docker_client
from mcontrol.templates import templates

router = APIRouter()


def _pill(request: Request, state: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_state_pill.html",
        context={"state": state},
    )


@router.post("/servers/{name}/lifecycle/start", response_class=HTMLResponse)
async def start(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    await docker_client.start(db.container_name_for(server))
    db.update_server_state(name=name, state="running")
    return _pill(request, "running")


@router.post("/servers/{name}/lifecycle/stop", response_class=HTMLResponse)
async def stop(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    await docker_client.stop(db.container_name_for(server))
    db.update_server_state(name=name, state="exited")
    return _pill(request, "exited")


@router.post("/servers/{name}/lifecycle/restart", response_class=HTMLResponse)
async def restart(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    await docker_client.restart(db.container_name_for(server))
    db.update_server_state(name=name, state="running")
    return _pill(request, "running")
