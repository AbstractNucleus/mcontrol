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

import asyncio
import os
import shutil
import stat
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from mcontrol import db, file_safety
from mcontrol.file_writer import atomic_write_stream_async, atomic_write_text_async
from mcontrol.templates import templates

router = APIRouter()

_TEXT_VIEW_BYTES_MAX = 5 * 1024 * 1024
_BINARY_SNIFF_BYTES = 8 * 1024


def _server_or_404(name: str) -> dict:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


def _list_dir(target: Path, base: Path) -> list[dict]:
    entries: list[dict] = []
    for child in target.iterdir():
        try:
            st = child.lstat()
        except OSError:
            continue
        if file_safety.is_special(st.st_mode):
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
    target = file_safety.resolve_within(server["dir"], path)
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
    target = file_safety.resolve_within(server["dir"], path)
    st = file_safety.stat_regular_file(target)

    base = Path(server["dir"]).resolve()
    rel = target.relative_to(base).as_posix()
    size = st.st_size

    def _sniff() -> bytes:
        with target.open("rb") as f:
            return f.read(_BINARY_SNIFF_BYTES)

    sniff = await asyncio.to_thread(_sniff)
    is_binary = b"\x00" in sniff

    if is_binary:
        return templates.TemplateResponse(
            request=request,
            name="_file_view.html",
            context={
                "mode": "binary",
                "server_name": name,
                "filename": rel,
                "size": size,
                "mtime_ns": st.st_mtime_ns,
            },
        )
    if size > _TEXT_VIEW_BYTES_MAX:
        return templates.TemplateResponse(
            request=request,
            name="_file_view.html",
            context={
                "mode": "too_large",
                "server_name": name,
                "filename": rel,
                "size": size,
                "mtime_ns": st.st_mtime_ns,
            },
        )
    content = await asyncio.to_thread(
        target.read_text, encoding="utf-8", errors="replace"
    )
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

    _invalidate_search_index(name)
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
        # design — child symlinks are unlinked as entries, never followed.
        shutil.rmtree(target)
    else:
        os.unlink(target)

    _invalidate_search_index(name)
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

    _invalidate_search_index(name)
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
    target = file_safety.resolve_within(server["dir"], path)

    try:
        target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="path not found") from exc

    file_safety.validate_upload_filename(new_name)

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

    _invalidate_search_index(name)
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

    _invalidate_search_index(name)
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

    Reuses `file_safety.stat_regular_file` so symlinks, directories, special files,
    traversal, and missing paths all refuse identically to the view
    endpoint. The browser triggers a save dialog because FileResponse
    sets `Content-Disposition: attachment; filename="..."` when `filename`
    is provided.
    """
    server = _server_or_404(name)
    target = file_safety.resolve_within(server["dir"], path)
    file_safety.stat_regular_file(target)
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


# --- search index cache ---------------------------------------------------
#
# Per-server in-memory index of (name_lower, relpath, kind) tuples plus a
# boolean recording whether the default skip-set actually pruned anything
# during the walk. The endpoint is fired on every debounced keystroke, so
# memoising the walk is the win — see issue #49.
#
# The cache lives in the process; we assume single-process operation
# (panel runs as one uvicorn worker). Multi-worker invalidation is
# explicitly out of scope.
#
# Each server has two slots: the default `index` (skip-set applied at
# build time, per issue #50) and a separate `index_with_chunks` populated
# lazily when an operator passes `include_chunks=1`. Keeping them
# separate avoids re-walking on every toggle and avoids storing a
# superset that would then need re-filtering at query time.

_INDEX_TTL_SECONDS = 60.0

# Module-level cache. Each value is a dict with optional `default` and
# `with_chunks` slots; each slot is `(built_at, entries, skipped_flag)`.
_search_index: dict[str, dict[str, tuple[float, list[tuple[str, str, str]], bool]]] = {}


def _now() -> float:
    """Monotonic clock used for TTL checks. Indirected so tests can
    monkeypatch it without touching the global `time` module."""
    return time.monotonic()


def _invalidate_search_index(server_name: str) -> None:
    """Drop both cache slots for `server_name`. Called from every
    mutating handler. A no-op if the server has no cached index."""
    _search_index.pop(server_name, None)


def _build_index(
    base: Path, include_chunks: bool
) -> tuple[list[tuple[str, str, str]], bool]:
    """Walk `base` once and return (entries, skipped).

    `entries` is a list of `(name_lower, relpath, kind)` tuples; special
    files are filtered out at this stage. Symlinked directories are not
    descended (followlinks=False). When `include_chunks` is False the
    default skip-set (see `_SEARCH_DEFAULT_SKIP_DIRS`) is applied during
    the walk so chunk/region noise never enters the index.
    """
    entries: list[tuple[str, str, str]] = []
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
            full = Path(root) / entry_name
            try:
                st = full.lstat()
            except OSError:
                continue
            if file_safety.is_special(st.st_mode):
                continue
            kind = (
                "symlink" if stat.S_ISLNK(st.st_mode)
                else ("dir" if stat.S_ISDIR(st.st_mode) else "file")
            )
            rel = full.relative_to(base).as_posix()
            entries.append((entry_name.lower(), rel, kind))
    return entries, skipped


def _get_search_index(
    server_name: str, base: Path, include_chunks: bool
) -> tuple[list[tuple[str, str, str]], bool]:
    """Return the cached index for the (server, include_chunks) pair,
    rebuilding on miss or after TTL expiry."""
    slot_key = "with_chunks" if include_chunks else "default"
    server_slots = _search_index.get(server_name)
    if server_slots is not None:
        slot = server_slots.get(slot_key)
        if slot is not None:
            built_at, entries, skipped = slot
            if _now() - built_at < _INDEX_TTL_SECONDS:
                return entries, skipped

    entries, skipped = _build_index(base, include_chunks)
    _search_index.setdefault(server_name, {})[slot_key] = (
        _now(), entries, skipped,
    )
    return entries, skipped


@router.get("/servers/{name}/files/search", response_class=HTMLResponse)
async def search(
    request: Request,
    name: str,
    q: str = Query(""),
    include_chunks: bool = Query(False),
) -> HTMLResponse:
    """Recursive case-insensitive basename search (slice 5 PR 7).

    Consults a per-server in-memory index (built lazily, invalidated on
    mutation, TTL-refreshed) rather than re-walking on every keystroke
    — see issue #49. Symlinked directories are not descended at index
    build time; their link entries can still match by name. Special
    files are filtered at build time too. Capped at `_SEARCH_LIMIT` hits
    to keep render bounded on large trees.

    By default the index excludes well-known high-cardinality Minecraft
    world subdirs (chunk regions, per-player data, etc. — see
    `_SEARCH_DEFAULT_SKIP_DIRS`) when they sit under a `world` or `DIM*`
    parent. Pass `include_chunks=1` to query an alternate index that
    includes them.
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
    entries, skipped = await asyncio.to_thread(
        _get_search_index, name, base, include_chunks
    )

    results: list[dict] = []
    truncated = False
    for name_lower, rel, kind in entries:
        if needle not in name_lower:
            continue
        results.append({"name": Path(rel).name, "path": rel, "kind": kind})
        if len(results) >= _SEARCH_LIMIT:
            truncated = True
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


@router.post("/servers/{name}/files/bulk_delete")
async def bulk_delete(
    name: str,
    paths: list[str] = Form(...),  # noqa: B008 — FastAPI dep-injection idiom
    confirm: str = Form(""),
) -> Response:
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

    _invalidate_search_index(name)
    return Response(status_code=204)


@router.post("/servers/{name}/files/bulk_move")
async def bulk_move(
    name: str,
    sources: list[str] = Form(...),  # noqa: B008 — FastAPI dep-injection idiom
    dest_dir: str = Form(""),
) -> Response:
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

    _invalidate_search_index(name)
    return Response(status_code=204)
