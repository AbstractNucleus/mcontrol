"""Shared FastAPI dependencies for route modules."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import aiodocker
from fastapi import Depends, HTTPException, Request

from mcontrol.infra import db_async, server_lock


def get_docker(request: Request) -> aiodocker.Docker:
    """Return the lifespan-scoped aiodocker client (decision #98).

    Routes inject this via ``Depends(get_docker)`` and pass it into
    ``docker_client.*``, ``resources.*``, ``server_rcon.*``, etc. The
    single client is opened in ``mcontrol_dashboard.lifespan`` startup and
    closed on shutdown.
    """
    return request.app.state.docker


async def get_server_or_404(name: str) -> dict:
    server = await db_async.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


async def get_locked_server_or_404(request: Request, name: str) -> AsyncIterator[dict]:
    """Hold the fleet mutation lock and read current DB state inside it.

    Fleet-wide serialization also covers container-name aliases between rows.
    """
    base = Path(request.app.state.settings.server_base_path)
    async with server_lock.server_mutation_lock(base, "__fleet__"):
        server = await db_async.get_server(name)
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")
        yield server


def validate_uuid(uuid: str) -> str:
    try:
        return str(UUID(uuid))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid uuid") from exc


async def get_player_or_404(uuid: str = Depends(validate_uuid)) -> dict:
    player = await db_async.get_player(uuid)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player
