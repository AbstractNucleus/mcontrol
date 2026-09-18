"""Regenerate scaffold scripts with a diff-preview checkpoint.

The diff endpoint captures both files' mtimes and a fingerprint of the
rendered pair and its target. The confirm endpoint re-checks all three
under the fleet lock and aborts on drift. There is no merge logic. The
diff is the operator's checkpoint for clobbering hand-edits.

Flow:

  GET  /servers/{name}/regenerate          → unified diff + hidden mtimes
  POST /servers/{name}/regenerate/confirm  → re-stat; write atomically or 409
"""

import difflib
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import health, migration, scaffolding
from mcontrol.routes._dependencies import get_locked_server_or_404, get_server_or_404
from mcontrol.services import server_service
from mcontrol.templates import render_variables_card, templates

router = APIRouter()


def _compose_path(server_dir: Path) -> Path:
    return server_dir / "docker-compose.yml"


def _start_path(server_dir: Path) -> Path:
    return server_dir / "server" / "start_server.sh"


def _read_with_mtime(path: Path) -> tuple[str, int]:
    """Return (content, mtime_ns). Missing file → ("", 0). The 0 sentinel
    is matched on confirm so a file appearing under the operator's feet
    counts as drift the same way an edit does."""
    if not path.exists():
        return "", 0
    return path.read_text(encoding="utf-8"), path.stat().st_mtime_ns


def _disk_mtime(path: Path) -> int:
    return path.stat().st_mtime_ns if path.exists() else 0


def _diff(disk: str, rendered: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            disk.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=f"{label} (disk)",
            tofile=f"{label} (rendered)",
            n=3,
        )
    )


def _proposal_fingerprint(
    server: dict, rendered_compose: str, rendered_start: str
) -> str:
    """Bind a preview to both rendered bytes and the current DB target."""
    digest = hashlib.sha256()
    parts = (
        "mcontrol-regenerate-v1",
        str(server["name"]),
        str(server.get("container_name") or ""),
        str(Path(server["dir"]).resolve()),
        rendered_compose,
        rendered_start,
    )
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _variables_render_error(server: dict) -> str | None:
    try:
        return health.variables_render_error(server)
    except (AttributeError, TypeError) as exc:
        return str(exc) or "invalid variable data"


def _render_variables_error_card(
    request: Request, server: dict, error: str, *, status_code: int
) -> HTMLResponse:
    safe_server = (
        server
        if isinstance(server.get("variables"), dict)
        else {**server, "variables": {}}
    )
    return templates.TemplateResponse(
        request=request,
        name="_variables_card.html",
        context={
            "server": safe_server,
            "variables_error": error,
            "scripts_stale": None,
        },
        status_code=status_code,
    )


def _render_diff_partial(
    request: Request,
    server: dict,
    *,
    drifted: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    server_dir = Path(server["dir"])
    variables = server.get("variables") or {}

    rendered_compose = scaffolding.render_compose(server["name"], variables)
    rendered_start = scaffolding.render_start_script(variables)
    proposal_fingerprint = _proposal_fingerprint(
        server, rendered_compose, rendered_start
    )

    disk_compose, compose_mtime_ns = _read_with_mtime(_compose_path(server_dir))
    disk_start, start_mtime_ns = _read_with_mtime(_start_path(server_dir))

    return templates.TemplateResponse(
        request=request,
        name="_regenerate_diff.html",
        context={
            "server": server,
            "compose_diff": _diff(disk_compose, rendered_compose, "docker-compose.yml"),
            "start_diff": _diff(disk_start, rendered_start, "server/start_server.sh"),
            "compose_mtime_ns": compose_mtime_ns,
            "start_mtime_ns": start_mtime_ns,
            "proposal_fingerprint": proposal_fingerprint,
            "drifted": drifted,
        },
        status_code=status_code,
    )


@router.get("/servers/{name}/regenerate", response_class=HTMLResponse)
async def get(
    request: Request, server: dict = Depends(get_server_or_404)
) -> HTMLResponse:
    # If variables don't render, there is nothing meaningful to diff -
    # send the operator back to the card; the health banner on the
    # detail page already explains the variables-incomplete cause.
    variables_error = _variables_render_error(server)
    if variables_error is not None:
        return _render_variables_error_card(
            request, server, variables_error, status_code=200
        )
    return _render_diff_partial(request, server)


@router.post("/servers/{name}/regenerate/confirm", response_class=HTMLResponse)
async def confirm(
    request: Request,
    server: dict = Depends(get_locked_server_or_404),
    compose_mtime_ns: int = Form(...),
    start_mtime_ns: int = Form(...),
    proposal_fingerprint: str = Form(...),
) -> HTMLResponse:
    try:
        server_service.ensure_no_pending_migration(server)
    except migration.MigrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    server_dir = Path(server["dir"])
    variables = server.get("variables") or {}

    variables_error = _variables_render_error(server)
    if variables_error is not None:
        return _render_variables_error_card(
            request, server, variables_error, status_code=409
        )

    rendered_compose = scaffolding.render_compose(server["name"], variables)
    rendered_start = scaffolding.render_start_script(variables)
    current_fingerprint = _proposal_fingerprint(
        server, rendered_compose, rendered_start
    )

    compose_path = _compose_path(server_dir)
    start_path = _start_path(server_dir)

    if (
        _disk_mtime(compose_path) != compose_mtime_ns
        or _disk_mtime(start_path) != start_mtime_ns
        or current_fingerprint != proposal_fingerprint
    ):
        return _render_diff_partial(request, server, drifted=True, status_code=409)

    try:
        scaffolding.write_scaffold_files(server_dir, server["name"], variables)
    except scaffolding.ScaffoldWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return render_variables_card(request, server)
