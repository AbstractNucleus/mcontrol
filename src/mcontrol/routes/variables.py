"""HTMX-driven Variables card on the detail page (slice 6 PR 3).

  GET  /servers/{name}/variables          → read card partial
  GET  /servers/{name}/variables?edit=1   → form partial
  POST /servers/{name}/variables          → write-back JSONB, re-render card

The card is gated on `server.scaffolded_at is not null` at the
template level; POST also refuses unscaffolded rows with 409 so a
direct edit cannot write JSONB on a legacy server.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import jar_picker, migration, server_variables_form
from mcontrol.domain.scaffolding import (
    DEFAULT_JAVA_VERSION,
    JAVA_VERSIONS,
    MEMORY_MIN_GB,
)
from mcontrol.routes._dependencies import get_locked_server_or_404, get_server_or_404
from mcontrol.services import server_service
from mcontrol.templates import render_variables_card, templates

router = APIRouter()


def _form(
    request: Request,
    server: dict,
    form: dict | None = None,
    errors: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    server_base_path = Path(request.app.state.settings.server_base_path)
    return templates.TemplateResponse(
        request=request,
        name="_variables_form.html",
        context={
            "server": server,
            "form": form,
            "errors": errors or {},
            "memory_min_gb": MEMORY_MIN_GB,
            "java_versions": JAVA_VERSIONS,
            "default_java_version": DEFAULT_JAVA_VERSION,
            "jar_options": jar_picker.existing_jars(
                Path(server["dir"]), server_base_path
            ),
        },
        status_code=status_code,
    )


@router.get("/servers/{name}/variables", response_class=HTMLResponse)
async def get(
    request: Request, server: dict = Depends(get_server_or_404), edit: int = 0
) -> HTMLResponse:
    if edit:
        return _form(request, server)
    return render_variables_card(request, server)


@router.post("/servers/{name}/variables", response_class=HTMLResponse)
async def post(
    request: Request,
    name: str,
    server: dict = Depends(get_locked_server_or_404),
    memory_budget_gb: int = Form(...),
    port: int = Form(...),
    server_jar: str = Form(""),
    java_version: int = Form(DEFAULT_JAVA_VERSION),
    jvm_extra_args: str = Form(""),
    custom_start_script: str | None = Form(None),
) -> HTMLResponse:
    try:
        server_service.ensure_no_pending_migration(server)
    except migration.MigrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if server.get("scaffolded_at") is None:
        raise HTTPException(
            status_code=409,
            detail="Variables are only editable on a scaffolded server.",
        )

    submitted = await request.form()
    form = {
        "memory_budget_gb": memory_budget_gb,
        "port": port,
        "server_jar": server_jar.strip(),
        "java_version": java_version,
        "jvm_extra_args": jvm_extra_args.strip(),
        "custom_start_script": (
            (custom_start_script or "").strip() if "custom_start_script" in submitted
            else (server.get("variables") or {}).get("custom_start_script", "")
        ),
    }
    errors = server_variables_form.validate(form)

    if not errors:
        collision = await server_variables_form.check_port_collision(name, port)
        if collision:
            errors["port"] = collision

    if errors:
        return _form(request, server, form=form, errors=errors, status_code=422)

    updated = await server_service.update_server_variables(
        name=name, server=server, new_values=form
    )
    refreshed = {**server, "variables": updated}
    return render_variables_card(request, refreshed)
