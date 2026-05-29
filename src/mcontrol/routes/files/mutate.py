"""Move/rename/delete endpoints, including bulk variants."""

import os
import shutil
import stat
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from mcontrol.infra import file_safety
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.routes.files._listing import _parent_listing
from mcontrol.services import file_search
from mcontrol.templates import templates

router = APIRouter()


def _resolve_and_classify(server_dir: str, path: str) -> tuple[Path, int]:
    """Resolve `path` under the server dir, lstat it, and refuse special
    files. Returns ``(target, lstat_mode)``; raises 404 if it vanished and
    400 for a block/char/fifo/socket. Shared by single and bulk delete so
    both observe the same path-safety contract; the path is echoed in the
    error for batch context.
    """
    target = file_safety.resolve_within(server_dir, path)
    try:
        st = target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"not found: {path}") from exc
    if file_safety.is_special(st.st_mode):
        raise HTTPException(
            status_code=400, detail=f"not a regular file or directory: {path}"
        )
    return target, st.st_mode


def _remove(target: Path, mode: int) -> None:
    """Delete one resolved entry: ``shutil.rmtree`` a real directory,
    ``os.unlink`` otherwise. An lstat mode is never ``S_ISDIR`` for a
    symlink, so symlinks (and files) unlink as entries and their targets
    are never followed. ``rmtree`` likewise refuses to descend through
    symlinked subdirs.
    """
    if stat.S_ISDIR(mode):
        shutil.rmtree(target)
    else:
        os.unlink(target)


def _plan_move(
    server_dir: str, source: str, dst_parent: Path, dst_resolved: Path
) -> tuple[Path, Path]:
    """Validate moving `source` into `dst_parent` and return ``(src, dest)``.

    Refuses a missing source, a no-op (dest dir is the source's current
    parent), a cyclic move (dest inside the source. the structure would
    loop), and a pre-existing collision (no force). Raises HTTPException
    with the offending path for batch context. Shared by single and bulk
    move.
    """
    src = file_safety.resolve_within(server_dir, source)
    try:
        src.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"source not found: {source}"
        ) from exc
    if dst_parent == src.parent:
        raise HTTPException(
            status_code=400,
            detail=f"destination is the source's current parent: {source}",
        )
    src_resolved = src.resolve(strict=False)
    if src_resolved == dst_resolved or src_resolved in dst_resolved.parents:
        raise HTTPException(
            status_code=400, detail=f"destination is inside the source: {source}"
        )
    dest = dst_parent / src.name
    try:
        dest.lstat()
    except FileNotFoundError:
        pass
    else:
        raise HTTPException(
            status_code=409, detail=f"already exists at destination: {src.name}"
        )
    return src, dest


def _tree_response(
    request: Request, name: str, server_dir: str, anchor: Path
) -> HTMLResponse:
    """Render the parent listing of `anchor` as the action's tree partial.

    The JS swaps it into the closest matching `<ul.file-tree__children>`.
    """
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={
            "server_name": name,
            "entries": _parent_listing(server_dir, anchor),
        },
    )


@router.post("/servers/{name}/files/delete", response_class=HTMLResponse)
async def delete(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Form(""),
    confirm_name: str = Form(""),
) -> HTMLResponse:
    """Delete a file, symlink, or directory.

    Files and symlinks delete one-shot. Directories are recursive and
    require `confirm_name` to match the directory's basename. the slice
    plan's "type-name confirmation" guard against accidental rmrf. The
    bind-mount root (`path=""`) is sacred and cannot be deleted.
    """
    if not path:
        raise HTTPException(status_code=400, detail="cannot delete server root")
    target, mode = _resolve_and_classify(server["dir"], path)
    if stat.S_ISDIR(mode) and confirm_name != target.name:
        raise HTTPException(
            status_code=400, detail=f"confirm_name must equal {target.name!r}"
        )
    _remove(target, mode)

    file_search.invalidate(name)
    return _tree_response(request, name, server["dir"], target)


@router.post("/servers/{name}/files/rename", response_class=HTMLResponse)
async def rename(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Form(""),
    new_name: str = Form(...),
) -> HTMLResponse:
    """Rename an entry within its current parent.

    Refuses `path=""` (server root has no parent), names that fail the
    upload-filename validator, and any pre-existing collision (no force).
    A no-op rename (`new_name` unchanged) re-renders the listing without
    touching disk so the client always sees a coherent tree.
    """
    if not path:
        raise HTTPException(status_code=400, detail="cannot rename server root")
    target = file_safety.resolve_within(server["dir"], path)

    try:
        target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="path not found") from exc

    file_safety.validate_upload_filename(new_name)

    if new_name != target.name:
        dest = target.parent / new_name
        try:
            dest.lstat()
        except FileNotFoundError:
            pass
        else:
            raise HTTPException(status_code=409, detail=f"already exists: {new_name}")
        os.rename(target, dest)
        file_search.invalidate(name)

    return _tree_response(request, name, server["dir"], target)


@router.post("/servers/{name}/files/move", response_class=HTMLResponse)
async def move(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    source: str = Form(""),
    dest_dir: str = Form(""),
) -> HTMLResponse:
    """Move an entry into a different directory, keeping its basename."""
    if not source:
        raise HTTPException(status_code=400, detail="cannot move server root")
    dst_parent = file_safety.resolve_within(server["dir"], dest_dir)
    if not dst_parent.exists():
        raise HTTPException(status_code=404, detail="destination not found")
    if not dst_parent.is_dir():
        raise HTTPException(status_code=400, detail="destination is not a directory")

    src, dest = _plan_move(
        server["dir"], source, dst_parent, dst_parent.resolve(strict=False)
    )
    os.rename(src, dest)

    file_search.invalidate(name)
    return _tree_response(request, name, server["dir"], src)


@router.post("/servers/{name}/files/bulk_delete")
async def bulk_delete(
    name: str,
    server: dict = Depends(get_server_or_404),
    paths: list[str] = Form(...),  # noqa: B008  (FastAPI dep-injection idiom)
    confirm: str = Form(""),
) -> Response:
    """Delete every entry in `paths` after a single operator-typed `DELETE`.

    The PR-4 per-dir basename-confirm doesn't scale to bulk; one global
    typed phrase covers the whole batch instead. Every entry is resolved
    and classified first so an illegal one refuses the whole batch rather
    than leaving the operator with mystery partial state.
    """
    if confirm != "DELETE":
        raise HTTPException(status_code=400, detail="confirm must be 'DELETE'")
    cleaned = [p for p in paths if p]
    if not cleaned:
        raise HTTPException(status_code=400, detail="no paths provided")
    if len(cleaned) != len(paths):
        raise HTTPException(status_code=400, detail="cannot delete server root")

    resolved = [_resolve_and_classify(server["dir"], p) for p in cleaned]
    for target, mode in resolved:
        _remove(target, mode)

    file_search.invalidate(name)
    return Response(status_code=204)


@router.post("/servers/{name}/files/bulk_move")
async def bulk_move(
    name: str,
    server: dict = Depends(get_server_or_404),
    sources: list[str] = Form(...),  # noqa: B008  (FastAPI dep-injection idiom)
    dest_dir: str = Form(""),
) -> Response:
    """Move every `sources` entry into `dest_dir`, keeping each basename.

    Validates the whole batch first (collision, cyclic move, no-op, missing
    source, root source, non-dir destination) so a validation failure
    causes no partial moves. Once validated, performs every os.rename; a
    later OS-level error is a system fault, not operator-recoverable, and
    is not rolled back.
    """
    if not sources:
        raise HTTPException(status_code=400, detail="no sources")
    if any(not s for s in sources):
        raise HTTPException(status_code=400, detail="cannot move server root")

    dst_parent = file_safety.resolve_within(server["dir"], dest_dir)
    if not dst_parent.exists():
        raise HTTPException(status_code=404, detail="destination not found")
    if not dst_parent.is_dir():
        raise HTTPException(status_code=400, detail="destination is not a directory")
    dst_resolved = dst_parent.resolve(strict=False)

    plan = [_plan_move(server["dir"], s, dst_parent, dst_resolved) for s in sources]
    for src, dest in plan:
        os.rename(src, dest)

    file_search.invalidate(name)
    return Response(status_code=204)
