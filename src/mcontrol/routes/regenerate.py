"""Regenerate scaffold scripts with a diff-preview checkpoint.

Decision 025: the diff endpoint captures both files' mtimes; the
confirm endpoint re-stats them and aborts on drift. atomic_write_text
keeps partial writes impossible. There is no merge logic — the diff
is the operator's checkpoint for clobbering hand-edits.

Flow:

  GET  /servers/{name}/regenerate          → unified diff + hidden mtimes
  POST /servers/{name}/regenerate/confirm  → re-stat; write atomically or 409
"""

import difflib
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from mcontrol import health, scaffolding
from mcontrol.file_writer import atomic_write_text
from mcontrol.routes._dependencies import get_server_or_404
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
            "drifted": drifted,
        },
        status_code=status_code,
    )


@router.get("/servers/{name}/regenerate", response_class=HTMLResponse)
async def get(
    request: Request, server: dict = Depends(get_server_or_404)
) -> HTMLResponse:
    # If variables don't render, there is nothing meaningful to diff —
    # send the operator back to the card; the health banner on the
    # detail page already explains the variables-incomplete cause.
    if health.variables_render_error(server) is not None:
        return render_variables_card(request, server)
    return _render_diff_partial(request, server)


@router.post("/servers/{name}/regenerate/confirm", response_class=HTMLResponse)
async def confirm(
    request: Request,
    server: dict = Depends(get_server_or_404),
    compose_mtime_ns: int = Form(...),
    start_mtime_ns: int = Form(...),
) -> HTMLResponse:
    server_dir = Path(server["dir"])
    variables = server.get("variables") or {}

    compose_path = _compose_path(server_dir)
    start_path = _start_path(server_dir)

    if (
        _disk_mtime(compose_path) != compose_mtime_ns
        or _disk_mtime(start_path) != start_mtime_ns
    ):
        return _render_diff_partial(request, server, drifted=True, status_code=409)

    rendered_compose = scaffolding.render_compose(server["name"], variables)
    rendered_start = scaffolding.render_start_script(variables)

    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server").mkdir(parents=True, exist_ok=True)
    atomic_write_text(compose_path, rendered_compose)
    atomic_write_text(start_path, rendered_start)
    start_path.chmod(0o755)

    return render_variables_card(request, server)
