"""Create/update endpoints: save (atomic text write), upload, mkdir."""

import stat
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from mcontrol import file_safety, file_search
from mcontrol.file_writer import atomic_write_stream_async, atomic_write_text_async
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.routes.files._safety import _list_dir
from mcontrol.templates import templates

router = APIRouter()


@router.post("/servers/{name}/files/save", response_class=HTMLResponse)
async def save(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Form(...),
    content: str = Form(...),
    mtime_ns: int = Form(...),
    force: bool = Form(False),
) -> HTMLResponse:
    target = file_safety.resolve_within(server["dir"], path)
    st = file_safety.stat_regular_file(target)

    base = Path(server["dir"]).resolve()
    rel = target.relative_to(base).as_posix()

    # Browsers send CRLF in form-encoded textareas; CodeMirror uses LF.
    # Normalise so the mtime check and on-disk content stay deterministic.
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    if not force and st.st_mtime_ns != mtime_ns:
        # The form's hx-target is the meta slot for successful saves (issue
        # #57). On conflict we need to swap the whole view so the editor
        # remounts with normalized content + banner — override the form's
        # target via htmx response headers.
        return templates.TemplateResponse(
            request=request,
            name="_file_view.html",
            context={
                "mode": "text",
                "server_name": name,
                "filename": rel,
                "content": normalized,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "conflict": True,
            },
            status_code=409,
            headers={"HX-Retarget": "#file-view", "HX-Reswap": "innerHTML"},
        )

    await atomic_write_text_async(target, normalized)
    new_st = target.stat()
    # Issue #57: success returns only the meta fragment so the swap doesn't
    # destroy the CodeMirror EditorView. The fragment carries the fresh
    # mtime_ns for the next save and the `saved` indicator.
    return templates.TemplateResponse(
        request=request,
        name="_file_editor_meta.html",
        context={
            "mtime_ns": new_st.st_mtime_ns,
            "saved": True,
        },
    )


@router.post("/servers/{name}/files/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Form(""),
    force: bool = Form(False),
    files: list[UploadFile] = File(...),  # noqa: B008 — FastAPI dep-injection idiom
) -> HTMLResponse:
    """Upload one-or-more files to a directory under the server's bind-mount.

    Conflict UX (per slice 5 plan): if any uploaded filename collides
    with an existing entry and `force` is not set, refuse the entire
    batch (no writes happen) and return HTTP 409 with a confirm-overwrite
    partial. The client re-POSTs with `force=true` to commit.

    Per-file writes are atomic (sibling tempfile + os.replace). The
    batch is *not* transactional — if file 7 of 10 fails after a clean
    conflict scan, files 1–6 are on disk. That's acceptable; the
    operator can re-upload the failed remainder.
    """
    target_dir = file_safety.resolve_within(server["dir"], path)
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")

    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    # Filename validation first — never let an invalid name reach disk.
    for f in files:
        file_safety.validate_upload_filename(f.filename or "")

    # Conflict scan: classify every existing target before any writes.
    # Hard refusals (dir, special) abort with 400 even when force=true —
    # the operator can't clobber these via this endpoint, and surfacing
    # them through the conflict modal would be misleading.
    conflicts: list[str] = []
    for f in files:
        target = target_dir / f.filename
        try:
            st = target.lstat()
        except FileNotFoundError:
            continue
        if file_safety.is_special(st.st_mode):
            raise HTTPException(
                status_code=400,
                detail=f"refusing to clobber special file: {f.filename}",
            )
        if stat.S_ISDIR(st.st_mode):
            raise HTTPException(
                status_code=400,
                detail=f"refusing to clobber directory: {f.filename}",
            )
        # Regular files and symlinks are surfaced as conflicts. Overwriting
        # a symlink via os.replace swaps the symlink itself (does not write
        # through), which is consistent with the "never follow symlinks"
        # contract.
        conflicts.append(f.filename)

    if conflicts and not force:
        return templates.TemplateResponse(
            request=request,
            name="_file_upload_conflict.html",
            context={
                "server_name": name,
                "path": path,
                "conflicts": conflicts,
            },
            status_code=409,
        )

    for f in files:
        target = target_dir / f.filename
        await atomic_write_stream_async(target, f.file)

    file_search.invalidate(name)
    base = Path(server["dir"]).resolve()
    entries = _list_dir(target_dir, base)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.post("/servers/{name}/files/mkdir", response_class=HTMLResponse)
async def mkdir(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Form(""),
    dirname: str = Form(...),
) -> HTMLResponse:
    """Create an empty directory `dirname` inside `path` (the parent dir)."""
    parent = file_safety.resolve_within(server["dir"], path)
    if not parent.exists():
        raise HTTPException(status_code=404, detail="parent not found")
    if not parent.is_dir():
        raise HTTPException(status_code=400, detail="parent is not a directory")

    file_safety.validate_upload_filename(dirname)

    target = parent / dirname
    # `lstat` catches both regular collisions and existing symlinks.
    try:
        target.lstat()
    except FileNotFoundError:
        target.mkdir()
    else:
        raise HTTPException(status_code=409, detail=f"already exists: {dirname}")

    file_search.invalidate(name)
    base = Path(server["dir"]).resolve()
    entries = _list_dir(parent, base)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )
