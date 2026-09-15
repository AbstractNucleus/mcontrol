"""Archive API; filesystem and decoder work never runs on the event loop."""

import asyncio

from fastapi import APIRouter, Depends, Form
from fastapi.responses import Response

from mcontrol.infra import server_lock
from mcontrol.routes._dependencies import get_locked_server_or_404, get_server_or_404
from mcontrol.services import file_archive, file_search

router = APIRouter()


@router.get("/servers/{name}/files/archive-capabilities")
async def archive_capabilities(server: dict = Depends(get_server_or_404)) -> dict[str, bool]:
    return await asyncio.to_thread(file_archive.capabilities)


@router.post("/servers/{name}/files/extract", status_code=204)
async def extract(
    name: str,
    server: dict = Depends(get_locked_server_or_404),
    path: str = Form(...),
    dest_dir: str = Form(""),
) -> Response:
    await server_lock.drain_on_cancel(
        asyncio.to_thread(file_archive.extract, server["dir"], path, dest_dir)
    )
    file_search.invalidate(name)
    return Response(status_code=204)


@router.post("/servers/{name}/files/compress", status_code=204)
async def compress(
    name: str,
    server: dict = Depends(get_locked_server_or_404),
    paths: list[str] = Form(...),  # noqa: B008 (FastAPI form injection)
    dest_dir: str = Form(""),
    archive_name: str = Form(...),
    format: str = Form(...),
) -> Response:
    await server_lock.drain_on_cancel(
        asyncio.to_thread(
            file_archive.compress, server["dir"], paths, dest_dir, archive_name, format
        )
    )
    file_search.invalidate(name)
    return Response(status_code=204)
