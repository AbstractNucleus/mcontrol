"""Thin wrapper over supabase-py, scoped to app_mcontrol.servers.

All callers go through list_servers / get_server / upsert_server. The
underlying client is constructed lazily on first use and cached for the
lifetime of the process.
"""

from typing import Any

from supabase import Client, create_client

from mcontrol.settings import Settings

_SCHEMA = "app_mcontrol"
_TABLE = "servers"

_client_singleton: Client | None = None


def _client() -> Client:
    global _client_singleton
    if _client_singleton is None:
        settings = Settings()
        _client_singleton = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _client_singleton


def _table():
    return _client().schema(_SCHEMA).table(_TABLE)


def list_servers() -> list[dict[str, Any]]:
    response = _table().select("*").order("name").execute()
    return response.data


def get_server(name: str) -> dict[str, Any] | None:
    response = _table().select("*").eq("name", name).limit(1).execute()
    return response.data[0] if response.data else None


def upsert_server(*, name: str, dir: str, state: str) -> None:
    _table().upsert(
        {"name": name, "dir": dir, "state": state},
        on_conflict="name",
    ).execute()
