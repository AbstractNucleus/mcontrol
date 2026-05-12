"""HTMX-driven inline edit for the per-server `container_name` override
and `dir`. Decision 021 — the operator's safety valve against drift."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from mcontrol import db
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.templates import templates

router = APIRouter()


def _card(request: Request, server: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_bindings_card.html",
        context={"server": server},
    )


def _form(request: Request, server: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_bindings_form.html",
        context={"server": server},
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
    dir: str = Form(...),
) -> HTMLResponse:
    # Empty string means "clear the override and fall back to name".
    cn_value: str | None = container_name.strip() or None
    db.update_bindings(name=name, container_name=cn_value, dir=dir)

    refreshed = {**server, "container_name": cn_value, "dir": dir}
    return _card(request, refreshed)
