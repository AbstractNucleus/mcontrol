"""GET + POST /servers/new — scaffold a new server.

DB-first ordering (slice 6 plan):

  1. Insert row with state='scaffolding' + variables JSONB.
  2. mkdir + render templates + atomic-write files.
  3. Update row with state='created' + scaffolded_at=now().

If anything between (1) and (3) raises, best-effort rollback both
sides: rmtree(<dir>) + db.delete_server(name), then re-raise as 500.
The rollback flow lives in ``services.server_service.scaffold_new_server``.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from mcontrol import db_async, server_variables_form
from mcontrol.server_variables_form import LOADERS
from mcontrol.services import server_service
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()


_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")


def _render_form(
    request: Request,
    form: dict,
    errors: dict[str, str],
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="new_server.html",
        context={"form": form, "errors": errors, "loaders": LOADERS},
        status_code=status_code,
    )


def _validate_static(form: dict) -> dict[str, str]:
    """Validate fields against shape rules (no DB / disk lookups)."""
    errors = server_variables_form.validate(form)

    if not _NAME_RE.match(form["name"]):
        errors["name"] = (
            "3–32 chars; lowercase letters, digits, and hyphens; must start with a letter."
        )
    if not form["accept_eula"]:
        errors["accept_eula"] = "You must accept the Minecraft EULA to create a server."

    return errors


@router.get("/servers/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return _render_form(request, form={}, errors={})


@router.post("/servers/new", response_model=None)
async def new_submit(
    request: Request,
    name: str = Form(...),
    memory_budget_gb: int = Form(...),
    port: int = Form(...),
    server_jar: str = Form(...),
    loader: str = Form("vanilla"),
    jvm_extra_args: str = Form(""),
    accept_eula: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    form = {
        "name": name.strip(),
        "memory_budget_gb": memory_budget_gb,
        "port": port,
        "server_jar": server_jar.strip(),
        "loader": loader,
        "jvm_extra_args": jvm_extra_args.strip(),
        "accept_eula": bool(accept_eula),
    }
    errors = _validate_static(form)

    settings: Settings = request.app.state.settings
    base = Path(settings.server_base_path).resolve()

    target: Path | None = None
    if not errors:
        # Belt-and-suspenders containment per the slice 6 path-safety
        # contract — slug regex already forbids `/` and `.`, so this is
        # defence in depth, not load-bearing.
        target = (base / form["name"]).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            errors["name"] = "Invalid path."

    if not errors:
        servers = await db_async.list_servers()
        if any(row["name"] == form["name"] for row in servers):
            errors["name"] = "Server name already in use."
        elif target is not None and target.exists():
            errors["name"] = "Directory already exists."
        else:
            collision = await server_variables_form.check_port_collision(None, form["port"])
            if collision:
                errors["port"] = collision
            else:
                bound = server_variables_form.check_port_bound(form["port"])
                if bound:
                    errors["port"] = bound

    if errors:
        return _render_form(request, form=form, errors=errors, status_code=422)

    assert target is not None  # narrow for type-checkers; unreachable when no errors

    variables: dict = {
        "memory_budget_gb": form["memory_budget_gb"],
        "port": form["port"],
        "server_jar": form["server_jar"],
    }
    if form["jvm_extra_args"]:
        variables["jvm_extra_args"] = form["jvm_extra_args"]

    try:
        await server_service.scaffold_new_server(
            name=form["name"],
            target=target,
            variables=variables,
            loader=form["loader"],
            base=base,
        )
    except server_service.ScaffoldError as exc:
        raise HTTPException(status_code=500, detail=exc.detail) from None

    return RedirectResponse(url=f"/servers/{form['name']}", status_code=303)
