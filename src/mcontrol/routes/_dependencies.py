"""Shared FastAPI dependencies for route modules."""

from uuid import UUID

from fastapi import Depends, HTTPException

from mcontrol import db


def get_server_or_404(name: str) -> dict:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


def validate_uuid(uuid: str) -> str:
    try:
        return str(UUID(uuid))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid uuid") from exc


def get_player_or_404(uuid: str = Depends(validate_uuid)) -> dict:
    player = db.get_player(uuid)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player
