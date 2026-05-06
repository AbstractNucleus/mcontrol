"""Delete-server flow with type-name confirm + tombstone (decision 026).

  GET  /servers/{name}/delete   → confirm partial (type-name input)
  POST /servers/{name}/delete   → re-checks state, tombstones <dir>,
                                  deletes the row, returns HX-Redirect /

The Delete button on the detail page is disabled when state='running'.
The POST endpoint re-checks state at request time (returns 409) so a
race where the operator starts the server in another tab between
page render and confirm-click still refuses cleanly. Files aren't
removed — the dir is renamed to `<base>/.deleted-<name>-<unix-ts>/`
and discovery's dot-prefix filter (PR 5 also lands that) keeps the
tombstone invisible to subsequent scans.
"""

import time
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import db
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()


def _server_or_404(name: str) -> dict:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


def _partial(
    request: Request,
    server: dict,
    *,
    confirm: bool,
    error: str | None = None,
    typed: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_delete_confirm.html",
        context={
            "server": server,
            "confirm": confirm,
            "error": error,
            "typed": typed,
        },
        status_code=status_code,
    )


@router.get("/servers/{name}/delete", response_class=HTMLResponse)
async def get(request: Request, name: str, confirm: int = 0) -> HTMLResponse:
    server = _server_or_404(name)
    return _partial(request, server, confirm=bool(confirm))


@router.post("/servers/{name}/delete", response_class=HTMLResponse)
async def post(
    request: Request,
    name: str,
    confirm_name: str = Form(""),
) -> HTMLResponse:
    server = _server_or_404(name)

    # Re-check state at request time — protects against the operator
    # starting the server in another tab between page render and click.
    if server.get("state") == "running":
        raise HTTPException(
            status_code=409, detail="Stop the server before deleting."
        )

    if confirm_name.strip() != name:
        return _partial(
            request,
            server,
            confirm=True,
            error=f"Type the server name ({name!r}) exactly to confirm.",
            typed=confirm_name,
            status_code=422,
        )

    settings: Settings = request.app.state.settings
    base = Path(settings.server_base_path).resolve()
    server_dir = Path(server["dir"]).resolve()
    tomb_path = base / f".deleted-{name}-{int(time.time())}"

    if server_dir.exists():
        server_dir.rename(tomb_path)

    db.delete_server(name)

    response = HTMLResponse("", status_code=200)
    # HTMX picks up this header and navigates the browser to /. The
    # detail page's #delete-confirm target was the form's swap target;
    # without HX-Redirect we'd swap an empty body into it and the user
    # would still be on a page whose row no longer exists.
    response.headers["HX-Redirect"] = "/"
    return response
