"""HTMX-driven Variables card on the detail page (slice 6 PR 3).

  GET  /servers/{name}/variables          → read card partial
  GET  /servers/{name}/variables?edit=1   → form partial
  POST /servers/{name}/variables          → write-back JSONB, re-render card

The card is gated on `server.scaffolded_at is not null` at the
template level, but these endpoints don't enforce that — a non-
scaffolded row's edit POST would still write JSONB. The detail page
is the only entry point in the UI.
"""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import db, health
from mcontrol.templates import templates

router = APIRouter()

_PORT_MIN = 1024
_PORT_MAX = 65535
_MEMORY_MIN_GB = 2


def _server_or_404(name: str) -> dict:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


def _card(request: Request, server: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_variables_card.html",
        context={
            "server": server,
            "variables_error": health.variables_render_error(server),
            "scripts_stale": health.compute_scripts_stale(server),
        },
    )


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


def _validate(form: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if form["memory_budget_gb"] < _MEMORY_MIN_GB:
        errors["memory_budget_gb"] = f"Minimum {_MEMORY_MIN_GB} GB."
    if not (_PORT_MIN <= form["port"] <= _PORT_MAX):
        errors["port"] = f"Port must be between {_PORT_MIN} and {_PORT_MAX}."
    if not form["server_jar"].strip():
        errors["server_jar"] = "Required."
    return errors


@router.get("/servers/{name}/variables", response_class=HTMLResponse)
async def get(request: Request, name: str, edit: int = 0) -> HTMLResponse:
    server = _server_or_404(name)
    if edit:
        return _form(request, server)
    return _card(request, server)


@router.post("/servers/{name}/variables", response_class=HTMLResponse)
async def post(
    request: Request,
    name: str,
    memory_budget_gb: int = Form(...),
    port: int = Form(...),
    server_jar: str = Form(...),
    jvm_extra_args: str = Form(""),
) -> HTMLResponse:
    server = _server_or_404(name)
    form = {
        "memory_budget_gb": memory_budget_gb,
        "port": port,
        "server_jar": server_jar.strip(),
        "jvm_extra_args": jvm_extra_args.strip(),
    }
    errors = _validate(form)

    if not errors:
        for row in db.list_servers():
            if row["name"] == name:
                continue
            row_vars = row.get("variables") or {}
            if row_vars.get("port") == port:
                errors["port"] = (
                    f"Port {port} is already used by '{row['name']}'."
                )
                break

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

    db.update_variables(name=name, variables=updated)

    refreshed = {**server, "variables": updated}
    return _card(request, refreshed)
