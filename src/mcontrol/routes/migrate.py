"""Per-server legacy-to-scaffold migration card + run endpoint (slice 8 PR 1).

One-shot, opt-in, one-way. Once `scaffolded_at` is stamped the row is
treated identically to a slice-6 scaffolded row. The card disappears,
the form is gone, no rollback button.

  GET  /servers/{name}/migrate    → form partial (lazy-loaded by the
                                    detail page so the parse stays off
                                    the main render path); 404 if the
                                    row is already scaffolded.
  POST /servers/{name}/migrate    → validate form, re-check state +
                                    scaffolded_at, run migration, stamp
                                    the row, HX-Redirect to detail page.

The scaffolded stamp and variables are written atomically after file conversion.
A durable on-disk intent makes retries converge if the database response or
request connection is lost. Coordination lives in
``services.server_service.migrate_legacy_server``.
"""

from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import jar_picker, lifecycle_state, migration, server_variables_form
from mcontrol.domain.scaffolding import (
    DEFAULT_JAVA_VERSION,
    JAVA_VERSIONS,
    MEMORY_MIN_GB,
)
from mcontrol.infra import db, db_async, docker_client
from mcontrol.routes._dependencies import (
    get_docker,
    get_locked_server_or_404,
    get_server_or_404,
)
from mcontrol.services import server_service
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()


def _initial_form(server: dict) -> dict:
    """Pre-populated form values from the legacy parse, falling back to
    `server.variables` when present (some legacy rows acquired a partial
    JSONB through the discovery path)."""
    server_dir = Path(server["dir"])
    existing = server.get("variables") or {}
    pending = migration.latest_recoverable_backup(server_dir)
    if pending is not None:
        intent = migration.read_migration_intent(server_dir, pending)
        if intent["files_ready"]:
            parsed = intent["variables"]
            existing = {}
        else:
            parsed = migration.parse_legacy_variables(server_dir)
    else:
        parsed = migration.parse_legacy_variables(server_dir)
    return {
        "memory_budget_gb": parsed.get(
            "memory_budget_gb", existing.get("memory_budget_gb", "")
        ),
        "port": parsed.get("port", existing.get("port", "")),
        "server_jar": parsed.get("server_jar", existing.get("server_jar", "")),
        "jvm_extra_args": parsed.get(
            "jvm_extra_args", existing.get("jvm_extra_args", "")
        ),
        "java_version": parsed.get(
            "java_version", existing.get("java_version", DEFAULT_JAVA_VERSION)
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
    server_base_path = Path(request.app.state.settings.server_base_path)
    pending = migration.latest_recoverable_backup(server_dir)
    if error_banner is None and pending is not None:
        intent = migration.read_migration_intent(server_dir, pending)
        if intent["files_ready"]:
            error_banner = "An unfinished migration will resume using its saved values."
    return templates.TemplateResponse(
        request=request,
        name="_migrate_card.html",
        context={
            "server": server,
            "form": form,
            "errors": errors or {},
            "error_banner": error_banner,
            "running": lifecycle_state.is_running(server),
            "legacy_filenames": [p.name for p in migration.legacy_files(server_dir)],
            "memory_min_gb": MEMORY_MIN_GB,
            "java_versions": JAVA_VERSIONS,
            "default_java_version": DEFAULT_JAVA_VERSION,
            "jar_options": jar_picker.existing_jars(server_dir, server_base_path),
        },
        status_code=status_code,
    )


@router.get("/servers/{name}/migrate", response_class=HTMLResponse)
async def get_card(
    request: Request, server: dict = Depends(get_server_or_404)
) -> HTMLResponse:
    if server.get("scaffolded_at") is not None:
        raise HTTPException(status_code=404, detail="Server is already scaffolded.")
    return _render_card(request, server)


@router.post("/servers/{name}/migrate", response_class=HTMLResponse)
async def run_migration(
    request: Request,
    name: str,
    server: dict = Depends(get_locked_server_or_404),
    memory_budget_gb: int = Form(...),
    port: int = Form(...),
    server_jar: str = Form(...),
    java_version: int = Form(DEFAULT_JAVA_VERSION),
    jvm_extra_args: str = Form(""),
    docker: aiodocker.Docker = Depends(get_docker),
) -> HTMLResponse:
    if server.get("scaffolded_at") is not None:
        raise HTTPException(status_code=409, detail="Server is already scaffolded.")
    form = {
        "memory_budget_gb": memory_budget_gb,
        "port": port,
        "server_jar": server_jar.strip(),
        "java_version": java_version,
        "jvm_extra_args": jvm_extra_args.strip(),
    }
    errors = server_variables_form.validate(form)
    if not errors:
        collision = await server_variables_form.check_port_collision(name, port)
        if collision is not None:
            errors["port"] = collision

    if errors:
        return _render_card(
            request, server, form=form, errors=errors, status_code=422
        )

    settings: Settings = request.app.state.settings
    base = Path(settings.server_base_path).resolve()
    server_dir = Path(server["dir"]).resolve()
    try:
        server_dir.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid path.") from exc

    variables = server_variables_form.build_variables(form)

    container_name = db.container_name_for(server)
    if container_name != name:
        return _render_card(
            request,
            server,
            form=form,
            error_banner=(
                f"Bindings points this server at container {container_name!r}, but migration "
                f"would create {name!r}. Clear the container-name override before migrating."
            ),
            status_code=409,
        )
    for other in await db_async.list_servers():
        if other["name"] != name and db.container_name_for(other) == container_name:
            return _render_card(
                request,
                server,
                form=form,
                error_banner=(
                    f"Another server, {other['name']!r}, is bound to container "
                    f"{container_name!r}. Fix Bindings before migrating."
                ),
                status_code=409,
            )
    try:
        container_state = await docker_client.container_state(docker, container_name)
    except Exception:
        return _render_card(
            request,
            server,
            form=form,
            error_banner=(
                "Could not confirm the container is stopped. Check Docker and retry; "
                "no migration files were changed."
            ),
            status_code=409,
        )
    if container_state not in {None, "created", "exited", "dead"}:
        return _render_card(
            request,
            server,
            form=form,
            error_banner=(
                f"Docker reports the container is {container_state}. "
                "Stop it before migrating."
            ),
            status_code=409,
        )

    try:
        await server_service.migrate_legacy_server(
            name=name, variables=variables, server_dir=server_dir
        )
    except migration.MigrationError as exc:
        return _render_card(
            request,
            server,
            form=form,
            error_banner=str(exc),
            status_code=409,
        )

    response = HTMLResponse("", status_code=200)
    response.headers["HX-Redirect"] = f"/servers/{name}"
    return response
