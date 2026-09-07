"""HTMX-driven inline edit for the per-server `container_name` override
and `dir`. The operator's safety valve against drift."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from mcontrol.infra import db_async
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.services import server_service
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()


def _card(request: Request, server: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_bindings_card.html",
        context={"server": server},
    )


def _form(
    request: Request,
    server: dict,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_bindings_form.html",
        context={"server": server, "error": error},
        status_code=status_code,
    )


@router.get("/servers/{name}/bindings", response_class=HTMLResponse)
async def get(
    request: Request, server: dict = Depends(get_server_or_404), edit: int = 0
) -> HTMLResponse:
    if edit:
        return _form(request, server)
    return _card(request, server)


@router.post("/servers/{name}/bindings", response_class=HTMLResponse)
async def post(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    container_name: str = Form(""),
    dir: str = Form(""),
) -> HTMLResponse:
    # Empty string means "clear the override and fall back to name".
    cn_value: str | None = container_name.strip() or None

    settings: Settings = request.app.state.settings
    base = Path(settings.server_base_path).resolve()
    target = Path(dir).resolve()
    error: str | None = None
    try:
        target.relative_to(base)
    except ValueError:
        error = f"Directory must be under {base}."
    else:
        if not target.is_dir():
            error = "Directory does not exist on disk."
        else:
            for row in await db_async.list_servers():
                if row["name"] == name:
                    continue
                other = row.get("dir")
                if other and Path(other).resolve() == target:
                    error = (
                        f"Directory is already bound to '{row['name']}'."
                    )
                    break

    if error:
        return _form(
            request,
            {**server, "container_name": cn_value, "dir": dir},
            error=error,
            status_code=422,
        )

    resolved = str(target)
    await server_service.update_server_bindings(
        name=name, container_name=cn_value, dir=resolved
    )

    refreshed = {**server, "container_name": cn_value, "dir": resolved}
    return _card(request, refreshed)
