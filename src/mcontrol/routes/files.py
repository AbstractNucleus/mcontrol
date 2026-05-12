"""File tree + view + save + upload + delete + mkdir + rename + move + download + search + bulk.

Slice 5 PR 1 shipped tree + view. PR 2 added POST /files/save (CodeMirror
edit, atomic write, mtime check). PR 3 added POST /files/upload (multipart,
atomic per file, refuse-on-conflict with operator-confirmed force overwrite).
PR 4 added POST /files/delete (file or recursive directory; dir requires
type-name confirmation) and POST /files/mkdir. PR 5 added POST /files/rename,
POST /files/move, and the dirs-only `?picker=1` tree variant. PR 6 added
GET /files/download — single-file FileResponse with attachment disposition.
PR 7 (final) adds GET /files/search (case-insensitive recursive basename
match, capped), POST /files/bulk_delete (operator types DELETE once),
POST /files/bulk_move (refuse-on-any-collision).

Path-safety contract (mirrors slice 5 plan; applies to every endpoint):

1. Resolve `(<dir>) / operator_path` and refuse `..` traversal.
2. Walk every component with `Path.is_symlink()` — refuse to follow
   any segment that is a symlink. Symlinks are still rendered in
   listings (with a marker) but never traversed for read or write.
3. Sub-path check: the resolved target must live inside the resolved
   row `dir`. HTTP 400 otherwise.
4. Special files (`S_ISBLK` / `S_ISCHR` / `S_ISFIFO` / `S_ISSOCK`) are
   skipped from listings and rejected at endpoints.
5. Upload + mkdir filenames are operator-controlled; refuse `/`, `\\`,
   `..`, `.`, empty, and null-byte names before anything touches disk.
6. Delete refuses `path=""` (the server's bind-mount root is sacred)
   and refuses to follow symlinks — `os.unlink` removes the link entry,
   never the target.
"""

import os
import shutil
import stat
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

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
    picker: bool = Query(False),
) -> HTMLResponse:
    """Render a directory listing.

    `picker=1` returns a dirs-only variant via `_file_dir_picker.html` for
    the move-destination modal (slice 5 PR 5). Lazy-load uses the same
    endpoint with the same flag so child fetches stay dirs-only.
    """
    server = _server_or_404(name)
    target = _resolve_within(server["dir"], path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")

    base = Path(server["dir"]).resolve()
    entries = _list_dir(target, base)
    if picker:
        entries = [e for e in entries if e["kind"] == "dir"]
        return templates.TemplateResponse(
            request=request,
            name="_file_dir_picker.html",
            context={"server_name": name, "entries": entries},
        )
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


def _parent_listing(server_dir: str, target: Path) -> tuple[Path, list[dict]]:
    """Return (parent_dir, listing) for use as the action response.

    Delete and mkdir both refresh the parent of their target — the JS
    swaps that listing into the closest matching `<ul.file-tree__children>`.
    """
    base = Path(server_dir).resolve()
    parent = target.parent if target != base else base
    return parent, _list_dir(parent, base)


@router.post("/servers/{name}/files/delete", response_class=HTMLResponse)
async def delete(
    request: Request,
    name: str,
    path: str = Form(""),
    confirm_name: str = Form(""),
) -> HTMLResponse:
    """Delete a file, symlink, or directory.

    Files and symlinks delete one-shot. Directories are recursive and
    require `confirm_name` to match the directory's basename — the slice
    plan's "type-name confirmation" guard against accidental rmrf.

    The bind-mount root (`path=""`) is sacred and cannot be deleted.
    Symlinks are unlinked as link entries; their targets are never
    followed, consistent with the slice's path-safety contract.
    """
    server = _server_or_404(name)
    if not path:
        raise HTTPException(status_code=400, detail="cannot delete server root")
    target = _resolve_within(server["dir"], path)

    try:
        st = target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc

    if _is_special(st.st_mode):
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
        # design — child symlinks are unlinked as entries, never followed.
        shutil.rmtree(target)
    else:
        os.unlink(target)

    _, entries = _parent_listing(server["dir"], target)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.post("/servers/{name}/files/mkdir", response_class=HTMLResponse)
async def mkdir(
    request: Request,
    name: str,
    path: str = Form(""),
    dirname: str = Form(...),
) -> HTMLResponse:
    """Create an empty directory `dirname` inside `path` (the parent dir)."""
    server = _server_or_404(name)
    parent = _resolve_within(server["dir"], path)
    if not parent.exists():
        raise HTTPException(status_code=404, detail="parent not found")
    if not parent.is_dir():
        raise HTTPException(status_code=400, detail="parent is not a directory")

    _validate_upload_filename(dirname)

    target = parent / dirname
    # `lstat` catches both regular collisions and existing symlinks.
    try:
        target.lstat()
    except FileNotFoundError:
        target.mkdir()
    else:
        raise HTTPException(status_code=409, detail=f"already exists: {dirname}")

    base = Path(server["dir"]).resolve()
    entries = _list_dir(parent, base)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.post("/servers/{name}/files/rename", response_class=HTMLResponse)
async def rename(
    request: Request,
    name: str,
    path: str = Form(""),
    new_name: str = Form(...),
) -> HTMLResponse:
    """Rename an entry within its current parent.

    Refuses `path=""` (server root has no parent), names that fail the
    upload-filename validator, and any pre-existing collision (no force).
    """
    server = _server_or_404(name)
    if not path:
        raise HTTPException(status_code=400, detail="cannot rename server root")
    target = _resolve_within(server["dir"], path)

    try:
        target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="path not found") from exc

    _validate_upload_filename(new_name)

    if new_name == target.name:
        # No-op rename — pretend success without touching disk so the
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
    source: str = Form(""),
    dest_dir: str = Form(""),
) -> HTMLResponse:
    """Move an entry into a different directory, keeping its basename.

    Refuses moving the server root, no-op moves (`dest_dir == source.parent`),
    moving a directory into itself or any descendant (would loop), and any
    pre-existing collision at the destination (no force).
    """
    server = _server_or_404(name)
    if not source:
        raise HTTPException(status_code=400, detail="cannot move server root")
    src = _resolve_within(server["dir"], source)
    dst_parent = _resolve_within(server["dir"], dest_dir)

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

    # Refuse moving a directory into itself or any of its descendants —
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

    _, entries = _parent_listing(server["dir"], src)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.get("/servers/{name}/files/download")
async def download(
    name: str,
    path: str = Query(...),
) -> FileResponse:
    """Stream a single regular file to the operator with attachment disposition.

    Reuses `_stat_regular_file` so symlinks, directories, special files,
    traversal, and missing paths all refuse identically to the view
    endpoint. The browser triggers a save dialog because FileResponse
    sets `Content-Disposition: attachment; filename="..."` when `filename`
    is provided.
    """
    server = _server_or_404(name)
    target = _resolve_within(server["dir"], path)
    _stat_regular_file(target)
    return FileResponse(
        target,
        filename=target.name,
        media_type="application/octet-stream",
    )


_SEARCH_LIMIT = 200
_SEARCH_MIN_LEN = 2

# High-cardinality subdirs inside a Minecraft world whose contents are
# addressed by machine-generated names (chunk regions, per-player data
# files, etc.). They almost never match operator-meaningful queries but
# saturate the result cap with noise. The skip only fires when the dir
# sits directly under a `world`-named or `DIM*`-prefixed parent so a
# top-level dir that happens to share a name is searched normally.
_SEARCH_DEFAULT_SKIP_DIRS = frozenset({
    "region",
    "entities",
    "poi",
    "playerdata",
    "stats",
    "advancements",
})


def _is_world_like_parent(parent_name: str) -> bool:
    return parent_name == "world" or parent_name.startswith("DIM")


@router.get("/servers/{name}/files/search", response_class=HTMLResponse)
async def search(
    request: Request,
    name: str,
    q: str = Query(""),
    include_chunks: bool = Query(False),
) -> HTMLResponse:
    """Recursive case-insensitive basename search (slice 5 PR 7).

    Filename match only — no full-text grep, per slice contract.
    Symlinked directories are not descended (followlinks=False); their
    link entries can still match by name. Special files are skipped.
    Capped at `_SEARCH_LIMIT` hits to keep both walk and render bounded
    on large `world/region/` style trees.

    By default the walk prunes well-known high-cardinality Minecraft
    world subdirs (chunk regions, per-player data, etc. — see
    `_SEARCH_DEFAULT_SKIP_DIRS`) when they sit under a `world` or `DIM*`
    parent. Pass `include_chunks=1` to disable the prune.
    """
    server = _server_or_404(name)
    needle = q.strip().lower()
    if len(needle) < _SEARCH_MIN_LEN:
        return templates.TemplateResponse(
            request=request,
            name="_file_search_results.html",
            context={
                "server_name": name,
                "q": q,
                "results": [],
                "truncated": False,
                "too_short": bool(needle),
                "skipped": False,
            },
        )

    base = Path(server["dir"]).resolve()
    results: list[dict] = []
    truncated = False
    skipped = False
    for root, dirs, files in os.walk(base, followlinks=False):
        dirs.sort()
        files.sort()
        if not include_chunks and _is_world_like_parent(Path(root).name):
            keep = [d for d in dirs if d not in _SEARCH_DEFAULT_SKIP_DIRS]
            if len(keep) != len(dirs):
                skipped = True
                dirs[:] = keep
        for entry_name in dirs + files:
            if needle not in entry_name.lower():
                continue
            full = Path(root) / entry_name
            try:
                st = full.lstat()
            except OSError:
                continue
            if _is_special(st.st_mode):
                continue
            kind = (
                "symlink" if stat.S_ISLNK(st.st_mode)
                else ("dir" if stat.S_ISDIR(st.st_mode) else "file")
            )
            rel = full.relative_to(base).as_posix()
            results.append({"name": entry_name, "path": rel, "kind": kind})
            if len(results) >= _SEARCH_LIMIT:
                truncated = True
                break
        if truncated:
            break

    return templates.TemplateResponse(
        request=request,
        name="_file_search_results.html",
        context={
            "server_name": name,
            "q": q,
            "results": results,
            "truncated": truncated,
            "too_short": False,
            "skipped": skipped,
        },
    )


@router.post("/servers/{name}/files/bulk_delete", response_class=HTMLResponse)
async def bulk_delete(
    request: Request,
    name: str,
    paths: list[str] = Form(...),  # noqa: B008 — FastAPI dep-injection idiom
    confirm: str = Form(""),
) -> HTMLResponse:
    """Delete every entry in `paths` (regular files, symlinks, or recursive
    directories) after a single operator-typed `DELETE` confirmation.

    The PR-4 per-dir basename-confirm doesn't scale to bulk; one global
    typed phrase covers the whole batch instead. Each entry observes the
    same path-safety contract as single delete: refuse symlinks-as-path-
    components, refuse special files, refuse `paths == [""]` (root).
    """
    server = _server_or_404(name)
    if confirm != "DELETE":
        raise HTTPException(status_code=400, detail="confirm must be 'DELETE'")
    cleaned = [p for p in paths if p]
    if not cleaned:
        raise HTTPException(status_code=400, detail="no paths provided")
    if any(not p for p in paths) or "" in cleaned:
        # Defence-in-depth: refuse any empty-string path even mixed in.
        raise HTTPException(status_code=400, detail="cannot delete server root")

    # Resolve + classify everything first so we can refuse the whole batch
    # if any single entry is illegal — partial deletes with a 400 mid-way
    # would leave the operator with mystery state.
    resolved: list[tuple[Path, int]] = []
    for p in cleaned:
        target = _resolve_within(server["dir"], p)
        try:
            st = target.lstat()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"not found: {p}") from exc
        if _is_special(st.st_mode):
            raise HTTPException(status_code=400, detail=f"refuses special file: {p}")
        resolved.append((target, st.st_mode))

    for target, mode in resolved:
        if stat.S_ISLNK(mode):
            os.unlink(target)
        elif stat.S_ISDIR(mode):
            shutil.rmtree(target)
        else:
            os.unlink(target)

    base = Path(server["dir"]).resolve()
    entries = _list_dir(base, base)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )


@router.post("/servers/{name}/files/bulk_move", response_class=HTMLResponse)
async def bulk_move(
    request: Request,
    name: str,
    sources: list[str] = Form(...),  # noqa: B008 — FastAPI dep-injection idiom
    dest_dir: str = Form(""),
) -> HTMLResponse:
    """Move every `sources` entry into `dest_dir`, keeping each basename.

    Refuses the entire batch (no partial moves) on any collision at the
    destination, any cyclic move (dest inside source), any no-op
    (dest == source.parent), missing source, root source, or a non-dir
    destination. Once validated, performs every os.rename without rolling
    back if a later one trips an OS-level error — that's a system fault,
    not an operator-recoverable one.
    """
    server = _server_or_404(name)
    if not sources:
        raise HTTPException(status_code=400, detail="no sources")
    if any(not s for s in sources):
        raise HTTPException(status_code=400, detail="cannot move server root")

    dst_parent = _resolve_within(server["dir"], dest_dir)
    if not dst_parent.exists():
        raise HTTPException(status_code=404, detail="destination not found")
    if not dst_parent.is_dir():
        raise HTTPException(status_code=400, detail="destination is not a directory")
    dst_resolved = dst_parent.resolve(strict=False)

    plan: list[tuple[Path, Path]] = []
    for s in sources:
        src = _resolve_within(server["dir"], s)
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

    base = Path(server["dir"]).resolve()
    entries = _list_dir(base, base)
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )
