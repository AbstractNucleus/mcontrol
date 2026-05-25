"""Move/rename/delete endpoints, including bulk variants."""

import os
import shutil
import stat
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from mcontrol import file_safety, file_search
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.routes.files._safety import _parent_listing
from mcontrol.templates import templates

router = APIRouter()


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
    plan's "type-name confirmation" guard against accidental rmrf.

    The bind-mount root (`path=""`) is sacred and cannot be deleted.
    Symlinks are unlinked as link entries; their targets are never
    followed, consistent with the slice's path-safety contract.
    """
    if not path:
        raise HTTPException(status_code=400, detail="cannot delete server root")
    target = file_safety.resolve_within(server["dir"], path)

    try:
        st = target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc

    if file_safety.is_special(st.st_mode):
        raise HTTPException(status_code=400, detail="not a regular file or directory")

    if stat.S_ISLNK(st.st_mode):
        # Always one-shot; never follow.
        os.unlink(target)
    elif stat.S_ISDIR(st.st_mode):
        if confirm_name != target.name:
            raise HTTPException(
                status_code=400,
                detail=f"confirm_name must equal {target.name!r}",
            )
        # shutil.rmtree refuses to descend through symlinked subdirs by
        # design. child symlinks are unlinked as entries, never followed.
        shutil.rmtree(target)
    else:
        os.unlink(target)

    file_search.invalidate(name)
    _, entries = _parent_listing(server["dir"], target)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


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
    """
    if not path:
        raise HTTPException(status_code=400, detail="cannot rename server root")
    target = file_safety.resolve_within(server["dir"], path)

    try:
        target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="path not found") from exc

    file_safety.validate_upload_filename(new_name)

    if new_name == target.name:
        # No-op rename. pretend success without touching disk so the
        # client sees a coherent listing without any extra error path.
        _, entries = _parent_listing(server["dir"], target)
        return templates.TemplateResponse(
            request=request,
            name="_file_tree.html",
            context={"server_name": name, "entries": entries},
        )

    dest = target.parent / new_name
    try:
        dest.lstat()
    except FileNotFoundError:
        pass
    else:
        raise HTTPException(status_code=409, detail=f"already exists: {new_name}")

    os.rename(target, dest)

    file_search.invalidate(name)
    _, entries = _parent_listing(server["dir"], target)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.post("/servers/{name}/files/move", response_class=HTMLResponse)
async def move(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    source: str = Form(""),
    dest_dir: str = Form(""),
) -> HTMLResponse:
    """Move an entry into a different directory, keeping its basename.

    Refuses moving the server root, no-op moves (`dest_dir == source.parent`),
    moving a directory into itself or any descendant (would loop), and any
    pre-existing collision at the destination (no force).
    """
    if not source:
        raise HTTPException(status_code=400, detail="cannot move server root")
    src = file_safety.resolve_within(server["dir"], source)
    dst_parent = file_safety.resolve_within(server["dir"], dest_dir)

    try:
        src.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="source not found") from exc

    if not dst_parent.exists():
        raise HTTPException(status_code=404, detail="destination not found")
    if not dst_parent.is_dir():
        raise HTTPException(status_code=400, detail="destination is not a directory")

    if dst_parent == src.parent:
        raise HTTPException(status_code=400, detail="destination is the source's current parent")

    # Refuse moving a directory into itself or any of its descendants -
    # the resulting structure would be unreachable / cyclic.
    src_resolved = src.resolve(strict=False)
    dst_resolved = dst_parent.resolve(strict=False)
    if src_resolved == dst_resolved or src_resolved in dst_resolved.parents:
        raise HTTPException(
            status_code=400,
            detail="destination is inside the source",
        )

    dest = dst_parent / src.name
    try:
        dest.lstat()
    except FileNotFoundError:
        pass
    else:
        raise HTTPException(status_code=409, detail=f"already exists at destination: {src.name}")

    os.rename(src, dest)

    file_search.invalidate(name)
    _, entries = _parent_listing(server["dir"], src)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.post("/servers/{name}/files/bulk_delete")
async def bulk_delete(
    name: str,
    server: dict = Depends(get_server_or_404),
    paths: list[str] = Form(...),  # noqa: B008  (FastAPI dep-injection idiom)
    confirm: str = Form(""),
) -> Response:
    """Delete every entry in `paths` (regular files, symlinks, or recursive
    directories) after a single operator-typed `DELETE` confirmation.

    The PR-4 per-dir basename-confirm doesn't scale to bulk; one global
    typed phrase covers the whole batch instead. Each entry observes the
    same path-safety contract as single delete: refuse symlinks-as-path-
    components, refuse special files, refuse `paths == [""]` (root).
    """
    if confirm != "DELETE":
        raise HTTPException(status_code=400, detail="confirm must be 'DELETE'")
    cleaned = [p for p in paths if p]
    if not cleaned:
        raise HTTPException(status_code=400, detail="no paths provided")
    if any(not p for p in paths) or "" in cleaned:
        # Defence-in-depth: refuse any empty-string path even mixed in.
        raise HTTPException(status_code=400, detail="cannot delete server root")

    # Resolve + classify everything first so we can refuse the whole batch
    # if any single entry is illegal. partial deletes with a 400 mid-way
    # would leave the operator with mystery state.
    resolved: list[tuple[Path, int]] = []
    for p in cleaned:
        target = file_safety.resolve_within(server["dir"], p)
        try:
            st = target.lstat()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"not found: {p}") from exc
        if file_safety.is_special(st.st_mode):
            raise HTTPException(status_code=400, detail=f"refuses special file: {p}")
        resolved.append((target, st.st_mode))

    for target, mode in resolved:
        if stat.S_ISLNK(mode):
            os.unlink(target)
        elif stat.S_ISDIR(mode):
            shutil.rmtree(target)
        else:
            os.unlink(target)

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

    Refuses the entire batch (no partial moves) on any collision at the
    destination, any cyclic move (dest inside source), any no-op
    (dest == source.parent), missing source, root source, or a non-dir
    destination. Once validated, performs every os.rename without rolling
    back if a later one trips an OS-level error. that's a system fault,
    not an operator-recoverable one.
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

    plan: list[tuple[Path, Path]] = []
    for s in sources:
        src = file_safety.resolve_within(server["dir"], s)
        try:
            src.lstat()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"source not found: {s}") from exc

        if dst_parent == src.parent:
            raise HTTPException(
                status_code=400,
                detail=f"destination is the source's current parent: {s}",
            )
        src_resolved = src.resolve(strict=False)
        if src_resolved == dst_resolved or src_resolved in dst_resolved.parents:
            raise HTTPException(
                status_code=400,
                detail=f"destination is inside the source: {s}",
            )

        dest = dst_parent / src.name
        try:
            dest.lstat()
        except FileNotFoundError:
            pass
        else:
            raise HTTPException(
                status_code=409,
                detail=f"already exists at destination: {src.name}",
            )
        plan.append((src, dest))

    for src, dest in plan:
        os.rename(src, dest)

    file_search.invalidate(name)
    return Response(status_code=204)
