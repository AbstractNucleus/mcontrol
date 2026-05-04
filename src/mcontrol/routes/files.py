"""Read-only file tree + view + save + upload for a server's bind-mount directory.

Slice 5 PR 1 shipped tree + view. PR 2 added POST /files/save (CodeMirror
edit, atomic write, mtime check). PR 3 adds POST /files/upload (multipart,
atomic per file, refuse-on-conflict with operator-confirmed force overwrite).

Path-safety contract (mirrors slice 5 plan; applies to read, write, upload):

1. Resolve `(<dir>) / operator_path` and refuse `..` traversal.
2. Walk every component with `Path.is_symlink()` — refuse to follow
   any segment that is a symlink. Symlinks are still rendered in
   listings (with a marker) but never traversed for read or write.
3. Sub-path check: the resolved target must live inside the resolved
   row `dir`. HTTP 400 otherwise.
4. Special files (`S_ISBLK` / `S_ISCHR` / `S_ISFIFO` / `S_ISSOCK`) are
   skipped from listings and rejected at endpoints.
5. Upload filenames are operator-controlled; refuse `/`, `\\`, `..`, `.`,
   empty, and null-byte names before anything touches disk.
"""

import stat
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse

from mcontrol import db
from mcontrol.file_writer import atomic_write_stream, atomic_write_text
from mcontrol.templates import templates

router = APIRouter()

_TEXT_VIEW_BYTES_MAX = 5 * 1024 * 1024
_BINARY_SNIFF_BYTES = 8 * 1024


def _server_or_404(name: str) -> dict:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


def _is_special(mode: int) -> bool:
    return (
        stat.S_ISBLK(mode)
        or stat.S_ISCHR(mode)
        or stat.S_ISFIFO(mode)
        or stat.S_ISSOCK(mode)
    )


def _resolve_within(base_dir: str, operator_path: str) -> Path:
    """Resolve operator_path under base_dir per the path-safety contract.

    Returns an absolute path that is guaranteed to live inside the
    resolved base_dir, with no symlink in any intermediate component.
    The returned path may not exist — callers handle 404 themselves.
    """
    base = Path(base_dir).resolve()
    cleaned = operator_path.replace("\\", "/").lstrip("/")
    if "\x00" in cleaned:
        raise HTTPException(status_code=400, detail="invalid path")
    parts = [p for p in cleaned.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise HTTPException(status_code=400, detail="path traversal not allowed")

    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(status_code=400, detail="symlinks are not followed")

    try:
        current.resolve(strict=False).relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path outside server dir") from None
    return current


def _list_dir(target: Path, base: Path) -> list[dict]:
    entries: list[dict] = []
    for child in target.iterdir():
        try:
            st = child.lstat()
        except OSError:
            continue
        if _is_special(st.st_mode):
            continue
        rel = child.relative_to(base).as_posix()
        if child.is_symlink():
            kind = "symlink"
        elif stat.S_ISDIR(st.st_mode):
            kind = "dir"
        else:
            kind = "file"
        entries.append({"name": child.name, "path": rel, "kind": kind})
    entries.sort(key=lambda e: (0 if e["kind"] == "dir" else 1, e["name"].lower()))
    return entries


def _stat_regular_file(target: Path) -> "stat.os.stat_result":
    """Return lstat() of `target`, refusing symlinks/special/dirs.

    Caller must already have run `_resolve_within`. Raises 404 if the
    file vanished and 400 for symlink / special / directory.
    """
    try:
        st = target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    if stat.S_ISLNK(st.st_mode):
        raise HTTPException(status_code=400, detail="symlinks are not followed")
    if _is_special(st.st_mode):
        raise HTTPException(status_code=400, detail="not a regular file")
    if stat.S_ISDIR(st.st_mode):
        raise HTTPException(status_code=400, detail="not a file")
    return st


@router.get("/servers/{name}/files/tree", response_class=HTMLResponse)
async def tree(
    request: Request,
    name: str,
    path: str = Query(""),
) -> HTMLResponse:
    server = _server_or_404(name)
    target = _resolve_within(server["dir"], path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")

    base = Path(server["dir"]).resolve()
    entries = _list_dir(target, base)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.get("/servers/{name}/files/view", response_class=HTMLResponse)
async def view(
    request: Request,
    name: str,
    path: str = Query(...),
) -> HTMLResponse:
    server = _server_or_404(name)
    target = _resolve_within(server["dir"], path)
    st = _stat_regular_file(target)

    base = Path(server["dir"]).resolve()
    rel = target.relative_to(base).as_posix()
    size = st.st_size

    with target.open("rb") as f:
        sniff = f.read(_BINARY_SNIFF_BYTES)
    is_binary = b"\x00" in sniff

    if is_binary:
        return templates.TemplateResponse(
            request=request,
            name="_file_view.html",
            context={"mode": "binary", "filename": rel, "size": size},
        )
    if size > _TEXT_VIEW_BYTES_MAX:
        return templates.TemplateResponse(
            request=request,
            name="_file_view.html",
            context={"mode": "too_large", "filename": rel, "size": size},
        )
    content = target.read_text(encoding="utf-8", errors="replace")
    return templates.TemplateResponse(
        request=request,
        name="_file_view.html",
        context={
            "mode": "text",
            "server_name": name,
            "filename": rel,
            "content": content,
            "size": size,
            "mtime_ns": st.st_mtime_ns,
        },
    )


@router.post("/servers/{name}/files/save", response_class=HTMLResponse)
async def save(
    request: Request,
    name: str,
    path: str = Form(...),
    content: str = Form(...),
    mtime_ns: int = Form(...),
    force: bool = Form(False),
) -> HTMLResponse:
    server = _server_or_404(name)
    target = _resolve_within(server["dir"], path)
    st = _stat_regular_file(target)

    base = Path(server["dir"]).resolve()
    rel = target.relative_to(base).as_posix()

    # Browsers send CRLF in form-encoded textareas; CodeMirror uses LF.
    # Normalise so the mtime check and on-disk content stay deterministic.
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    if not force and st.st_mtime_ns != mtime_ns:
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
        )

    atomic_write_text(target, normalized)
    new_st = target.stat()
    return templates.TemplateResponse(
        request=request,
        name="_file_view.html",
        context={
            "mode": "text",
            "server_name": name,
            "filename": rel,
            "content": normalized,
            "size": new_st.st_size,
            "mtime_ns": new_st.st_mtime_ns,
            "saved": True,
        },
    )


def _validate_upload_filename(name: str) -> None:
    """Refuse any filename component the operator could weaponize.

    Multipart filenames are attacker-controlled and naive concatenation
    would let `foo/../../etc/passwd` escape the target dir. We forbid
    path separators, dot segments, empties and NULs before going near
    disk.
    """
    if not name:
        raise HTTPException(status_code=400, detail="empty filename")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail=f"invalid filename: {name!r}")
    if name in (".", ".."):
        raise HTTPException(status_code=400, detail=f"invalid filename: {name!r}")
    if "\x00" in name:
        raise HTTPException(status_code=400, detail="invalid filename")


@router.post("/servers/{name}/files/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    name: str,
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
    server = _server_or_404(name)
    target_dir = _resolve_within(server["dir"], path)
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")

    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    # Filename validation first — never let an invalid name reach disk.
    for f in files:
        _validate_upload_filename(f.filename or "")

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
        if _is_special(st.st_mode):
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
        atomic_write_stream(target, f.file)

    base = Path(server["dir"]).resolve()
    entries = _list_dir(target_dir, base)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )
