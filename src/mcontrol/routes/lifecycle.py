"""HTMX-driven Start / Stop / Restart for a server.

Each handler does the minimum required:

  Stop  → docker_client.stop(container_name); db.update_server_state(..., "exited")
  Start → if rcon_password missing: generate, persist, write .env, force-recreate.
          elif disk .env differs from DB rcon_password: write .env, force-recreate.
          else: docker_client.start(container_name).
          db.update_server_state(..., "running")
  Restart → same as Start, but uses docker_client.restart when .env already matches.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import compose_runner, db, docker_client, env_writer, passwords
from mcontrol.templates import templates

router = APIRouter()


def _pill(request: Request, state: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_state_pill.html",
        context={"state": state},
    )


def _ensure_env_matches_db(server: dict) -> bool:
    """Return True iff the .env on disk matches the DB rcon_password.
    If the password is missing in DB, it's generated and persisted.
    Returns True when no force-recreate is needed (DB matches disk),
    False otherwise (caller must force-recreate)."""
    name = server["name"]
    server_dir = Path(server["dir"])
    env_path = server_dir / ".env"

    db_password = server.get("rcon_password")
    if not db_password:
        db_password = passwords.generate()
        db.set_rcon_password(name=name, password=db_password)

    on_disk = env_writer.read_rcon_password(env_path)
    if on_disk == db_password:
        return True

    env_writer.write_rcon_password(env_path, db_password)
    return False


@router.post("/servers/{name}/lifecycle/start", response_class=HTMLResponse)
async def start(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    container_name = db.container_name_for(server)
    matches = _ensure_env_matches_db(server)
    if matches:
        await docker_client.start(container_name)
    else:
        await compose_runner.up_force_recreate(Path(server["dir"]))
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

    container_name = db.container_name_for(server)
    matches = _ensure_env_matches_db(server)
    if matches:
        await docker_client.restart(container_name)
    else:
        await compose_runner.up_force_recreate(Path(server["dir"]))
    db.update_server_state(name=name, state="running")
    return _pill(request, "running")
