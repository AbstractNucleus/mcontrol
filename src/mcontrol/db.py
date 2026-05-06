"""Thin wrapper over supabase-py, scoped to app_mcontrol.servers.

All callers go through the helpers below. The underlying client is
constructed lazily on first use and cached for the lifetime of the
process.
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


def insert_server(*, name: str, dir: str, state: str) -> None:
    """Create a new row. Used by discovery on first encounter only —
    subsequent scans use update_server_state so operator edits to dir
    and container_name survive."""
    _table().insert({"name": name, "dir": dir, "state": state}).execute()


def update_server_state(*, name: str, state: str) -> None:
    """Refresh a row's state. Does NOT touch dir or container_name."""
    _table().update({"state": state}).eq("name", name).execute()


def update_bindings(*, name: str, container_name: str | None, dir: str) -> None:
    """Operator-driven update of the row's container-name override and
    on-disk directory. `container_name=None` clears the override (back
    to falling back to `name`)."""
    _table().update(
        {"container_name": container_name, "dir": dir}
    ).eq("name", name).execute()


def container_name_for(server: dict[str, Any]) -> str:
    """Resolve the docker container name for a server row.

    Returns the explicit container_name override when set, otherwise
    falls back to the row's `name`. Decision 021.
    """
    override = server.get("container_name")
    if override:
        return override
    return server["name"]


# upsert_server stays as-is for any external caller; discovery no
# longer uses it. Slice 4 leaves the function in place so test_db's
# slice-3 upsert tests continue to pass without modification.
def upsert_server(*, name: str, dir: str, state: str) -> None:
    _table().upsert(
        {"name": name, "dir": dir, "state": state},
        on_conflict="name",
    ).execute()
