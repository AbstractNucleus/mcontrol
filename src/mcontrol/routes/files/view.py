"""Read-only file endpoints: text/binary view + download."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from mcontrol.infra import file_safety
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.routes.files._listing import _BINARY_SNIFF_BYTES, _TEXT_VIEW_BYTES_MAX
from mcontrol.templates import templates

router = APIRouter()


@router.get("/servers/{name}/files/view", response_class=HTMLResponse)
async def view(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Query(...),
) -> HTMLResponse:
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


@router.get("/servers/{name}/files/download")
async def download(
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Query(...),
) -> FileResponse:
    """Stream a single regular file to the operator with attachment disposition.

    Reuses `file_safety.stat_regular_file` so symlinks, directories, special files,
    traversal, and missing paths all refuse identically to the view
    endpoint. The browser triggers a save dialog because FileResponse
    sets `Content-Disposition: attachment; filename="..."` when `filename`
    is provided.
    """
    target = file_safety.resolve_within(server["dir"], path)
    file_safety.stat_regular_file(target)
    return FileResponse(
        target,
        filename=target.name,
        media_type="application/octet-stream",
    )
