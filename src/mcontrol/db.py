"""Thin wrapper over supabase-py, scoped to app_mcontrol.

All callers go through the helpers below. The underlying client is
constructed lazily on first use and cached for the lifetime of the
process.
"""

from datetime import UTC, datetime
from typing import Any

from supabase import Client, create_client

from mcontrol.settings import Settings

_SCHEMA = "app_mcontrol"
_TABLE = "servers"
_PLAYERS_TABLE = "players"

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


def _players_table():
    return _client().schema(_SCHEMA).table(_PLAYERS_TABLE)


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


def update_variables(*, name: str, variables: dict[str, Any]) -> None:
    """Replace the row's variables JSONB. Used by the Variables card
    write-back (slice 6 PR 3)."""
    _table().update({"variables": variables}).eq("name", name).execute()


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


def insert_scaffolding_server(*, name: str, dir: str, variables: dict[str, Any]) -> None:
    """Create a new mcontrol-scaffolded row in state='scaffolding'.

    Slice 6 PR 2 — first of the two DB writes that bracket the
    on-disk scaffold. mark_scaffolded transitions the row to 'created'
    once the files are written.
    """
    _table().insert(
        {"name": name, "dir": dir, "state": "scaffolding", "variables": variables}
    ).execute()


def mark_scaffolded(*, name: str) -> None:
    """Transition a row from state='scaffolding' to 'created' and stamp
    scaffolded_at=now(). Presence of scaffolded_at is the canonical
    'this row is mcontrol-scaffolded' signal (decision 023)."""
    _table().update(
        {"state": "created", "scaffolded_at": datetime.now(UTC).isoformat()}
    ).eq("name", name).execute()


def delete_server(name: str) -> None:
    """Hard-delete a row by name. Used by PR 2's rollback path and by
    PR 5's delete flow."""
    _table().delete().eq("name", name).execute()


# upsert_server stays as-is for any external caller; discovery no
# longer uses it. Slice 4 leaves the function in place so test_db's
# slice-3 upsert tests continue to pass without modification.
def upsert_server(*, name: str, dir: str, state: str) -> None:
    _table().upsert(
        {"name": name, "dir": dir, "state": state},
        on_conflict="name",
    ).execute()


# ---------------------------------------------------------------------------
# Player roster (slice 7, decision 027). Per-server whitelist/ops
# membership lives on disk; this table is identity-only.
# ---------------------------------------------------------------------------


def list_players() -> list[dict[str, Any]]:
    response = _players_table().select("*").order("name").execute()
    return response.data


def get_player(uuid: str) -> dict[str, Any] | None:
    response = _players_table().select("*").eq("uuid", uuid).limit(1).execute()
    return response.data[0] if response.data else None


def insert_player(*, uuid: str, name: str) -> None:
    """Insert a single roster row. Caller is responsible for ensuring
    uuid is unique; collisions raise from supabase-py."""
    _players_table().insert({"uuid": uuid, "name": name}).execute()


def insert_players_bulk(rows: list[dict[str, Any]]) -> None:
    """Insert many roster rows in a single PostgREST request — which
    PostgREST executes as a single SQL transaction. Used by slice 7
    PR 3's Import flow (decision 027). Empty list is a no-op."""
    if not rows:
        return
    _players_table().insert(rows).execute()


def delete_player(uuid: str) -> None:
    """Hard-delete a roster row by UUID. The cascade-confirm modal
    (slice 7 PR 4) is responsible for having already removed any
    per-server memberships that the operator chose to clear."""
    _players_table().delete().eq("uuid", uuid).execute()


def upsert_player_from_mojang(*, uuid: str, name: str) -> dict[str, Any]:
    """Upsert a roster row from a Mojang lookup result.

    Returns a dict describing the outcome so the caller can render the
    flash message:

      ``{"created": True,  "previous_name": None}``  — new row inserted.
      ``{"created": False, "previous_name": "<old>"}`` — UUID already
        present; ``previous_name`` is the value recorded *before* this
        call (equal to ``name`` when nothing changed).

    Refreshes ``name`` only when it differs from the stored value, to
    avoid pointless writes on the common already-current case.
    """
    existing = get_player(uuid)
    if existing is None:
        insert_player(uuid=uuid, name=name)
        return {"created": True, "previous_name": None}
    previous_name = existing["name"]
    if previous_name != name:
        _players_table().update({"name": name}).eq("uuid", uuid).execute()
    return {"created": False, "previous_name": previous_name}
