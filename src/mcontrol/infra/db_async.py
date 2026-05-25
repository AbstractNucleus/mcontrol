"""Async shim over the sync supabase-py helpers in ``mcontrol.db``.

Issue #99: ``supabase-py`` is a sync HTTP client, so every direct
``db.*`` call from an async route blocks the event loop on the
Supabase round-trip. ``healthz._probe_db`` already routes its
``db.ping`` through ``asyncio.to_thread``: this module is the same
pattern for every other PostgREST-hitting helper, so async callers
can ``await db_async.<fn>(...)`` and stop serializing the app on
database I/O.

Pure-Python helpers like ``db.container_name_for`` stay sync and are
called directly. wrapping them in ``to_thread`` would only add a
threadpool hop for no benefit.

Each wrapper resolves ``db.<fn>`` at call time, so test monkeypatches
of ``mcontrol.db`` still flow through.
"""

import asyncio
from typing import Any

from mcontrol.infra import db


async def list_servers() -> list[dict[str, Any]]:
    return await asyncio.to_thread(db.list_servers)


async def get_server(name: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(db.get_server, name)


async def insert_server(*, name: str, dir: str, state: str) -> None:
    await asyncio.to_thread(db.insert_server, name=name, dir=dir, state=state)


async def update_server_state(*, name: str, state: str) -> None:
    await asyncio.to_thread(db.update_server_state, name=name, state=state)


async def update_variables(*, name: str, variables: dict[str, Any]) -> None:
    await asyncio.to_thread(db.update_variables, name=name, variables=variables)


async def update_bindings(
    *, name: str, container_name: str | None, dir: str
) -> None:
    await asyncio.to_thread(
        db.update_bindings, name=name, container_name=container_name, dir=dir
    )


async def insert_scaffolding_server(
    *, name: str, dir: str, variables: dict[str, Any], loader: str
) -> None:
    await asyncio.to_thread(
        db.insert_scaffolding_server,
        name=name,
        dir=dir,
        variables=variables,
        loader=loader,
    )


async def mark_scaffolded(*, name: str) -> None:
    await asyncio.to_thread(db.mark_scaffolded, name=name)


async def delete_server(name: str) -> None:
    await asyncio.to_thread(db.delete_server, name)


async def list_players() -> list[dict[str, Any]]:
    return await asyncio.to_thread(db.list_players)


async def get_player(uuid: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(db.get_player, uuid)


async def insert_players_bulk(rows: list[dict[str, Any]]) -> None:
    await asyncio.to_thread(db.insert_players_bulk, rows)


async def delete_player(uuid: str) -> None:
    await asyncio.to_thread(db.delete_player, uuid)


async def upsert_player_from_mojang(*, uuid: str, name: str) -> dict[str, Any]:
    return await asyncio.to_thread(
        db.upsert_player_from_mojang, uuid=uuid, name=name
    )
