"""Per-server legacy-to-scaffold migration card + run endpoint (slice 8 PR 1).

Decision 028: one-shot, opt-in, one-way. Once `scaffolded_at` is stamped
the row is treated identically to a slice-6 scaffolded row. The card
disappears, the form is gone, no rollback button.

  GET  /servers/{name}/migrate    → form partial (lazy-loaded by the
                                    detail page so the parse stays off
                                    the main render path); 404 if the
                                    row is already scaffolded.
  POST /servers/{name}/migrate    → validate form, re-check state +
                                    scaffolded_at, run migration, stamp
                                    the row, HX-Redirect to detail page.

DB ordering mirrors `routes/new_server.py`: the "scaffolded" stamp is
the canonical marker, written *after* the file ops succeed. Failure
mid-stream leaves the row legacy; the operator re-clicks and the
idempotent migration converges.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import db, migration
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")
_PORT_MIN = 1024
_PORT_MAX = 65535
_MEMORY_MIN_GB = 2


def _server_or_404(name: str) -> dict:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


def _validate(form: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if form["memory_budget_gb"] < _MEMORY_MIN_GB:
        errors["memory_budget_gb"] = f"Minimum {_MEMORY_MIN_GB} GB."
    if not (_PORT_MIN <= form["port"] <= _PORT_MAX):
        errors["port"] = f"Port must be between {_PORT_MIN} and {_PORT_MAX}."
    if not form["server_jar"].strip():
        errors["server_jar"] = "Required."
    return errors


def _check_port_collision(name: str, port: int) -> str | None:
    for row in db.list_servers():
        if row["name"] == name:
            continue
        row_vars = row.get("variables") or {}
        if row_vars.get("port") == port:
            return f"Port {port} is already used by '{row['name']}'."
    return None


def _initial_form(server: dict) -> dict:
    """Pre-populated form values from the legacy parse, falling back to
    `server.variables` when present (some legacy rows acquired a partial
    JSONB through the discovery path)."""
    parsed = migration.parse_legacy_variables(Path(server["dir"]))
    existing = server.get("variables") or {}
    return {
        "memory_budget_gb": parsed.get(
            "memory_budget_gb", existing.get("memory_budget_gb", "")
        ),
        "port": parsed.get("port", existing.get("port", "")),
        "server_jar": parsed.get("server_jar", existing.get("server_jar", "")),
        "jvm_extra_args": parsed.get(
            "jvm_extra_args", existing.get("jvm_extra_args", "")
        ),
    }


def _render_card(
    request: Request,
    server: dict,
    *,
    form: dict | None = None,
    errors: dict[str, str] | None = None,
    error_banner: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    if form is None:
        form = _initial_form(server)
    server_dir = Path(server["dir"])
    return templates.TemplateResponse(
        request=request,
        name="_migrate_card.html",
        context={
            "server": server,
            "form": form,
            "errors": errors or {},
            "error_banner": error_banner,
            "running": server.get("state") == "running",
            "legacy_filenames": [p.name for p in migration.legacy_files(server_dir)],
        },
        status_code=status_code,
    )


@router.get("/servers/{name}/migrate", response_class=HTMLResponse)
async def get_card(request: Request, name: str) -> HTMLResponse:
    server = _server_or_404(name)
    if server.get("scaffolded_at") is not None:
        raise HTTPException(status_code=404, detail="Server is already scaffolded.")
    return _render_card(request, server)


@router.post("/servers/{name}/migrate", response_class=HTMLResponse)
async def run_migration(
    request: Request,
    name: str,
    memory_budget_gb: int = Form(...),
    port: int = Form(...),
    server_jar: str = Form(...),
    jvm_extra_args: str = Form(""),
) -> HTMLResponse:
    server = _server_or_404(name)

    if server.get("scaffolded_at") is not None:
        raise HTTPException(status_code=409, detail="Server is already scaffolded.")
    if server.get("state") == "running":
        raise HTTPException(status_code=409, detail="Stop the server before migrating.")

    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid server name.")

    form = {
        "memory_budget_gb": memory_budget_gb,
        "port": port,
        "server_jar": server_jar.strip(),
        "jvm_extra_args": jvm_extra_args.strip(),
    }
    errors = _validate(form)
    if not errors:
        collision = _check_port_collision(name, port)
        if collision is not None:
            errors["port"] = collision

    if errors:
        return _render_card(
            request, server, form=form, errors=errors, status_code=422
        )

    settings: Settings = request.app.state.settings
    base = Path(settings.server_base_path).resolve()
    target = (base / name).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid path.") from exc

    variables: dict = {
        "memory_budget_gb": form["memory_budget_gb"],
        "port": form["port"],
        "server_jar": form["server_jar"],
    }
    if form["jvm_extra_args"]:
        variables["jvm_extra_args"] = form["jvm_extra_args"]

    migration.migrate(name, variables, base)
    db.update_variables(name=name, variables=variables)
    db.mark_scaffolded(name=name)

    response = HTMLResponse("", status_code=200)
    response.headers["HX-Redirect"] = f"/servers/{name}"
    return response
