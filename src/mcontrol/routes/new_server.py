"""GET + POST /servers/new. scaffold a new server.

DB-first ordering (slice 6 plan):

  1. Insert row with state='scaffolding' + variables JSONB.
  2. mkdir + render templates + atomic-write files.
  3. Update row with state='created' + scaffolded_at=now().

If anything between (1) and (3) raises, best-effort rollback both
sides: rmtree(<dir>) + db.delete_server(name), then re-raise as 500.
The rollback flow lives in ``services.server_service.scaffold_new_server``.
"""

import asyncio
import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from mcontrol.domain import server_variables_form
from mcontrol.domain.scaffolding import (
    DEFAULT_JAVA_VERSION,
    JAVA_VERSIONS,
    MEMORY_MIN_GB,
    render_compose,
    render_server_properties,
    render_start_script,
)
from mcontrol.domain.server_variables_form import LOADERS, RESERVED_NAMES
from mcontrol.infra import db_async
from mcontrol.services import lifecycle_service, server_service
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()


_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")
_PREVIEW_DEFAULTS = {
    "name": "my-minecraft-server",
    "memory_budget_gb": 8,
    "port": 25565,
    "server_jar": "paper.jar",
    "loader": "vanilla",
    "java_version": DEFAULT_JAVA_VERSION,
}
_PREVIEW_RCON_PASSWORD = "GENERATED_ON_CREATE"


def _render_form(
    request: Request,
    form: dict,
    errors: dict[str, str],
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="new_server.html",
        context={
            "form": form,
            "errors": errors,
            "loaders": LOADERS,
            "memory_min_gb": MEMORY_MIN_GB,
            "java_versions": JAVA_VERSIONS,
            "default_java_version": DEFAULT_JAVA_VERSION,
        },
        status_code=status_code,
    )


def _validate_name(name: str) -> dict[str, str]:
    """Validate a server name without consulting the DB or filesystem."""
    errors: dict[str, str] = {}
    if not _NAME_RE.match(name):
        errors["name"] = (
            "3-32 chars; lowercase letters, digits, and hyphens; must start with a letter."
        )
    elif name in RESERVED_NAMES:
        errors["name"] = "This name is reserved."
    return errors


def _validate_static(form: dict) -> dict[str, str]:
    """Validate fields against shape rules (no DB / disk lookups)."""
    errors = server_variables_form.validate(form)
    errors.update(_validate_name(form["name"]))
    if not form["accept_eula"]:
        errors["accept_eula"] = "You must accept the Minecraft EULA to create a server."

    return errors


@router.get("/servers/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return _render_form(request, form={}, errors={})


def _preview_int(
    value: str, *, default: int, field: str, errors: dict[str, str]
) -> int:
    """Parse an integer preview field while keeping malformed input in JSON."""
    stripped = value.strip()
    if not stripped:
        return default
    try:
        return int(stripped)
    except ValueError:
        errors[field] = "Enter a whole number."
        return default


@router.post("/servers/new/preview")
async def new_preview(
    name: str = Form(""),
    memory_budget_gb: str = Form(""),
    port: str = Form(""),
    server_jar: str = Form(""),
    loader: str = Form(""),
    java_version: str = Form(""),
    jvm_extra_args: str = Form(""),
    custom_start_script: str = Form(""),
    accept_eula: str = Form(""),
) -> dict[str, object]:
    """Render a creation preview without probing or changing external state."""
    del accept_eula  # Previewing neither requires nor implies EULA acceptance.

    parse_errors: dict[str, str] = {}
    form = {
        "name": name.strip() or _PREVIEW_DEFAULTS["name"],
        "memory_budget_gb": _preview_int(
            memory_budget_gb,
            default=_PREVIEW_DEFAULTS["memory_budget_gb"],
            field="memory_budget_gb",
            errors=parse_errors,
        ),
        "port": _preview_int(
            port,
            default=_PREVIEW_DEFAULTS["port"],
            field="port",
            errors=parse_errors,
        ),
        "server_jar": server_jar.strip() or _PREVIEW_DEFAULTS["server_jar"],
        "loader": loader or _PREVIEW_DEFAULTS["loader"],
        "java_version": _preview_int(
            java_version,
            default=_PREVIEW_DEFAULTS["java_version"],
            field="java_version",
            errors=parse_errors,
        ),
        "jvm_extra_args": jvm_extra_args.strip(),
        "custom_start_script": custom_start_script.strip(),
    }

    errors = server_variables_form.validate(form)
    errors.update(_validate_name(form["name"]))
    errors.update(parse_errors)
    if errors:
        return {"files": [], "errors": errors}

    variables = server_variables_form.build_variables(form)
    return {
        "files": [
            {
                "path": "docker-compose.yml",
                "content": render_compose(form["name"], variables),
            },
            {
                "path": "server/start_server.sh",
                "content": render_start_script(variables),
            },
            {
                "path": "server/server.properties",
                "content": render_server_properties(_PREVIEW_RCON_PASSWORD),
            },
        ],
        "errors": {},
    }


@router.post("/servers/new", response_model=None)
async def new_submit(
    request: Request,
    name: str = Form(...),
    memory_budget_gb: int = Form(...),
    port: int = Form(...),
    server_jar: str = Form(""),
    loader: str = Form("vanilla"),
    java_version: int = Form(DEFAULT_JAVA_VERSION),
    jvm_extra_args: str = Form(""),
    custom_start_script: str = Form(""),
    accept_eula: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    form = {
        "name": name.strip(),
        "memory_budget_gb": memory_budget_gb,
        "port": port,
        "server_jar": server_jar.strip(),
        "loader": loader,
        "java_version": java_version,
        "jvm_extra_args": jvm_extra_args.strip(),
        "custom_start_script": custom_start_script.strip(),
        "accept_eula": bool(accept_eula),
    }
    errors = _validate_static(form)

    settings: Settings = request.app.state.settings
    base = Path(settings.server_base_path).resolve()

    target: Path | None = None
    if not errors:
        # Belt-and-suspenders containment per the slice 6 path-safety
        # contract. slug regex already forbids `/` and `.`, so this is
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
                host = lifecycle_service.probe_host()
                bound = await asyncio.to_thread(
                    server_variables_form.check_port_bound, form["port"], host
                )
                if bound:
                    errors["port"] = bound

    if errors:
        return _render_form(request, form=form, errors=errors, status_code=422)

    assert target is not None  # narrow for type-checkers; unreachable when no errors

    variables = server_variables_form.build_variables(form)

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
