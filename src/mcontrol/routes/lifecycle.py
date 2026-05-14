"""HTMX-driven Start / Stop / Restart for a server.

Each handler hits the Docker API directly and updates state. RCON
password lifecycle is operator-managed in `server/server.properties`
(decision 024) — mcontrol no longer touches `.env` here.

The response shape (slice 13, decision 033) is a single HTML body
carrying two HTMX swap targets:

- The state pill, which arrives at `#state-pill` as `outerHTML` (the
  default swap declared on the buttons).
- The lifecycle-buttons wrapper, marked `hx-swap-oob="true"` so HTMX
  swaps it into place at `#lifecycle-buttons` alongside the primary
  swap. This keeps the three buttons' disabled / accent state in
  lock-step with the freshly-updated state.
"""


from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from mcontrol import db, docker_client, lifecycle_state
from mcontrol.templates import templates

router = APIRouter()

_TIMEOUT_MSG = "Docker timed out — the container may still be starting. Try again."


def _pill_and_buttons(server: dict, state: str, *, flash: str | None = None) -> HTMLResponse:
    pill = templates.get_template("_state_pill.html").render({"state": state})
    buttons = templates.get_template("_lifecycle_buttons.html").render(
        {
            "server": server,
            "lifecycle": lifecycle_state.view(state),
            "oob": True,
        }
    )
    flash_html = templates.get_template("_lifecycle_flash.html").render(
        {"message": flash, "oob": True}
    )
    return HTMLResponse(pill + buttons + flash_html)


@router.post("/servers/{name}/lifecycle/start", response_class=HTMLResponse)
async def start(name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    try:
        await docker_client.start(db.container_name_for(server))
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    db.update_server_state(name=name, state="running")
    return _pill_and_buttons(server, "running")


@router.post("/servers/{name}/lifecycle/stop", response_class=HTMLResponse)
async def stop(name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    try:
        await docker_client.stop(db.container_name_for(server))
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    db.update_server_state(name=name, state="exited")
    return _pill_and_buttons(server, "exited")


@router.post("/servers/{name}/lifecycle/restart", response_class=HTMLResponse)
async def restart(name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    try:
        await docker_client.restart(db.container_name_for(server))
    except TimeoutError:
        return _pill_and_buttons(server, server.get("state") or "unknown", flash=_TIMEOUT_MSG)
    db.update_server_state(name=name, state="running")
    return _pill_and_buttons(server, "running")
