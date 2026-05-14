"""HTMX-driven Variables card on the detail page (slice 6 PR 3).

  GET  /servers/{name}/variables          → read card partial
  GET  /servers/{name}/variables?edit=1   → form partial
  POST /servers/{name}/variables          → write-back JSONB, re-render card

The card is gated on `server.scaffolded_at is not null` at the
template level, but these endpoints don't enforce that — a non-
scaffolded row's edit POST would still write JSONB. The detail page
is the only entry point in the UI.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from mcontrol import db_async, server_variables_form
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.templates import render_variables_card, templates

router = APIRouter()


def _form(
    request: Request,
    server: dict,
    form: dict | None = None,
    errors: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_variables_form.html",
        context={
            "server": server,
            "form": form,
            "errors": errors or {},
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
    server: dict = Depends(get_server_or_404),
    memory_budget_gb: int = Form(...),
    port: int = Form(...),
    server_jar: str = Form(...),
    jvm_extra_args: str = Form(""),
) -> HTMLResponse:
    form = {
        "memory_budget_gb": memory_budget_gb,
        "port": port,
        "server_jar": server_jar.strip(),
        "jvm_extra_args": jvm_extra_args.strip(),
    }
    errors = server_variables_form.validate(form)

    if not errors:
        collision = await server_variables_form.check_port_collision(name, port)
        if collision:
            errors["port"] = collision

    if errors:
        return _form(request, server, form=form, errors=errors, status_code=422)

    # Preserve any non-UI keys already present in the JSONB.
    existing = server.get("variables") or {}
    updated = {**existing, "memory_budget_gb": memory_budget_gb, "port": port,
               "server_jar": form["server_jar"]}
    if form["jvm_extra_args"]:
        updated["jvm_extra_args"] = form["jvm_extra_args"]
    else:
        updated.pop("jvm_extra_args", None)

    await db_async.update_variables(name=name, variables=updated)

    refreshed = {**server, "variables": updated}
    return render_variables_card(request, refreshed)
