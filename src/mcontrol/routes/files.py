"""Read-only file tree + view for a server's bind-mount directory.

Slice 5 PR 1. Path-safety contract (mirrors slice 5 plan):

1. Resolve `(<dir>) / operator_path` and refuse `..` traversal.
2. Walk every component with `Path.is_symlink()` — refuse to follow
   any segment that is a symlink. Symlinks are still rendered in
   listings (with a marker) but never traversed for read.
3. Sub-path check: the resolved target must live inside the resolved
   row `dir`. HTTP 400 otherwise.
4. Special files (`S_ISBLK` / `S_ISCHR` / `S_ISFIFO` / `S_ISSOCK`) are
   skipped from listings and rejected at endpoints.

Write paths (PR 2+) will inherit this same resolver.
"""

import stat
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from mcontrol import db
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
        context={"mode": "text", "filename": rel, "content": content, "size": size},
    )
