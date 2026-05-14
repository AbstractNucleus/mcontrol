"""Tests for the per-server Players card + add/flip routes (slice 7 PR 2)."""

import json
from pathlib import Path

import pytest

from mcontrol import db, membership, server_rcon

_NOTCH_UUID = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
_HEROBRINE_UUID = "ec561538-f3fd-461d-aff5-086b22154bce"


def _server_row(tmp_path: Path, *, state: str = "exited") -> dict:
    server_dir = tmp_path / "atm10"
    (server_dir / "server").mkdir(parents=True, exist_ok=True)
    return {
        "name": "atm10",
        "container_name": None,
        "dir": str(server_dir),
        "state": state,
        "scaffolded_at": None,
        "variables": {},
    }


@pytest.fixture
def fake_db(monkeypatch):
    """Stand-in for db.get_server / db.list_players / db.get_player.

    Yields a small mutable namespace the test can poke."""
    state = {
        "servers": {},
        "players": [],
    }

    def get_server(name):
        return state["servers"].get(name)

    def list_players():
        return list(state["players"])

    def get_player(uuid):
        for p in state["players"]:
            if p["uuid"] == uuid:
                return p
        return None

    monkeypatch.setattr(db, "get_server", get_server)
    monkeypatch.setattr(db, "list_players", list_players)
    monkeypatch.setattr(db, "get_player", get_player)
    return state


# ---------------------------------------------------------------------------
# GET /servers/{name}/players
# ---------------------------------------------------------------------------


async def test_get_returns_404_when_server_unknown(client, fake_db):
    response = await client.get("/servers/nope/players")
    assert response.status_code == 404


async def test_get_renders_empty_card_when_no_files(client, fake_db, tmp_path):
    fake_db["servers"]["atm10"] = _server_row(tmp_path)

    response = await client.get("/servers/atm10/players")

    assert response.status_code == 200
    body = response.text
    assert "No players on this server yet." in body
    # Form is always rendered.
    assert 'name="roster_uuid"' in body


async def test_get_combines_whitelist_and_ops_into_one_row_per_uuid(
    client, fake_db, tmp_path
):
    server = _server_row(tmp_path)
    fake_db["servers"]["atm10"] = server
    server_dir = Path(server["dir"])
    membership.add_whitelist_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(server_dir, uuid=_HEROBRINE_UUID, name="Herobrine")

    response = await client.get("/servers/atm10/players")
    body = response.text

    # Both names rendered.
    assert "Notch" in body
    assert "Herobrine" in body
    # Members are sorted by name (case-insensitive), so Herobrine comes first.
    herobrine_idx = body.index("Herobrine")
    notch_idx = body.index("Notch", herobrine_idx)
    herobrine_row = body[herobrine_idx:notch_idx]
    notch_row = body[notch_idx:]
    # Notch has both checkboxes ticked; Herobrine has only whitelist.
    # The form-end tags will appear after Notch's row too, so count the
    # `checked` keywords that appear before the next add-form section.
    notch_row = notch_row.split('class="players-card__add"')[0]
    assert herobrine_row.count("checked") == 1
    assert notch_row.count("checked") == 2


async def test_get_surfaces_malformed_whitelist_inline(client, fake_db, tmp_path):
    server = _server_row(tmp_path)
    fake_db["servers"]["atm10"] = server
    membership.whitelist_path(Path(server["dir"])).write_text("{not json")

    response = await client.get("/servers/atm10/players")

    assert response.status_code == 200
    assert "whitelist.json failed to parse" in response.text


async def test_get_renders_roster_picker(client, fake_db, tmp_path):
    fake_db["servers"]["atm10"] = _server_row(tmp_path)
    fake_db["players"] = [
        {"uuid": _NOTCH_UUID, "name": "Notch"},
        {"uuid": _HEROBRINE_UUID, "name": "Herobrine"},
    ]

    response = await client.get("/servers/atm10/players")

    body = response.text
    assert f'value="{_NOTCH_UUID}">Notch' in body
    assert f'value="{_HEROBRINE_UUID}">Herobrine' in body


async def test_get_shows_rcon_indicator_when_running_else_offline(
    client, fake_db, tmp_path
):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="running")
    body = (await client.get("/servers/atm10/players")).text
    assert "live (RCON)" in body

    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="exited")
    body = (await client.get("/servers/atm10/players")).text
    assert "offline (file edit)" in body


# ---------------------------------------------------------------------------
# POST /servers/{name}/players  (add from roster)
# ---------------------------------------------------------------------------


async def test_add_from_roster_offline_writes_to_whitelist_and_returns_card(
    client, fake_db, tmp_path
):
    server = _server_row(tmp_path, state="exited")
    fake_db["servers"]["atm10"] = server
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    response = await client.post(
        "/servers/atm10/players",
        data={"roster_uuid": _NOTCH_UUID},
    )

    assert response.status_code == 200
    entries, _ = membership.read_whitelist(Path(server["dir"]))
    assert entries == [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    # Op was NOT touched — picker defaults to whitelist-only.
    ops, _ = membership.read_ops(Path(server["dir"]))
    assert ops == []
    assert "added to the whitelist" in response.text


async def test_add_from_roster_returns_422_when_uuid_not_in_roster(
    client, fake_db, tmp_path
):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="exited")
    fake_db["players"] = []

    response = await client.post(
        "/servers/atm10/players",
        data={"roster_uuid": _NOTCH_UUID},
    )

    assert response.status_code == 422
    assert "not in the roster" in response.text


async def test_add_from_roster_returns_400_on_invalid_uuid(client, fake_db, tmp_path):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="exited")

    response = await client.post(
        "/servers/atm10/players",
        data={"roster_uuid": "not-a-uuid"},
    )

    assert response.status_code == 400


async def test_add_from_roster_running_uses_rcon(client, fake_db, tmp_path, monkeypatch):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="running")
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    captured: dict = {}

    async def fake_run(_docker, server, command):
        captured["command"] = command
        return "Added Notch to the whitelist"

    monkeypatch.setattr(server_rcon, "run_command", fake_run)

    response = await client.post(
        "/servers/atm10/players",
        data={"roster_uuid": _NOTCH_UUID},
    )

    assert response.status_code == 200
    assert captured["command"] == "whitelist add Notch"
    assert "Added Notch to the whitelist" in response.text


async def test_add_from_roster_running_surfaces_rcon_unavailable_as_error_flash(
    client, fake_db, tmp_path, monkeypatch
):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="running")
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    async def fake_run(_docker, server, command):
        raise server_rcon.RconUnavailable("RCON is not enabled in server.properties.")

    monkeypatch.setattr(server_rcon, "run_command", fake_run)

    response = await client.post(
        "/servers/atm10/players",
        data={"roster_uuid": _NOTCH_UUID},
    )

    assert response.status_code == 200
    assert "RCON is not enabled" in response.text
    assert "flash-msg--error" in response.text


# ---------------------------------------------------------------------------
# POST /servers/{name}/players/{uuid}/whitelist
# ---------------------------------------------------------------------------


async def test_toggle_whitelist_offline_adds_when_enabled_true(
    client, fake_db, tmp_path
):
    server = _server_row(tmp_path, state="exited")
    fake_db["servers"]["atm10"] = server
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    response = await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/whitelist",
        data={"enabled": "1"},
    )

    assert response.status_code == 200
    entries, _ = membership.read_whitelist(Path(server["dir"]))
    assert entries == [{"uuid": _NOTCH_UUID, "name": "Notch"}]


async def test_toggle_whitelist_offline_removes_when_enabled_false(
    client, fake_db, tmp_path
):
    server = _server_row(tmp_path, state="exited")
    fake_db["servers"]["atm10"] = server
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    membership.add_whitelist_entry(Path(server["dir"]), uuid=_NOTCH_UUID, name="Notch")

    response = await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/whitelist",
        data={"enabled": "0"},
    )

    assert response.status_code == 200
    entries, _ = membership.read_whitelist(Path(server["dir"]))
    assert entries == []


async def test_toggle_whitelist_running_uses_rcon_remove(
    client, fake_db, tmp_path, monkeypatch
):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="running")
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    captured: dict = {}

    async def fake_run(_docker, server, command):
        captured["command"] = command
        return "Removed Notch from the whitelist"

    monkeypatch.setattr(server_rcon, "run_command", fake_run)

    response = await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/whitelist",
        data={"enabled": "0"},
    )

    assert response.status_code == 200
    assert captured["command"] == "whitelist remove Notch"


async def test_toggle_whitelist_falls_back_to_disk_name_when_uuid_not_in_roster(
    client, fake_db, tmp_path
):
    """Pre-Import case: a UUID is on disk but not yet in the roster.
    The flip should still work, using the name from the on-disk entry."""
    server = _server_row(tmp_path, state="exited")
    fake_db["servers"]["atm10"] = server
    fake_db["players"] = []  # roster is empty
    membership.add_whitelist_entry(Path(server["dir"]), uuid=_NOTCH_UUID, name="Notch")

    response = await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/whitelist",
        data={"enabled": "0"},
    )

    assert response.status_code == 200
    entries, _ = membership.read_whitelist(Path(server["dir"]))
    assert entries == []


async def test_toggle_whitelist_returns_404_when_uuid_unresolvable(
    client, fake_db, tmp_path
):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="exited")
    fake_db["players"] = []

    response = await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/whitelist",
        data={"enabled": "1"},
    )

    assert response.status_code == 404


async def test_toggle_whitelist_returns_409_on_mtime_drift(
    client, fake_db, tmp_path, monkeypatch
):
    server = _server_row(tmp_path, state="exited")
    fake_db["servers"]["atm10"] = server
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    def boom(*args, **kwargs):
        raise membership.StaleWriteError("stale")

    monkeypatch.setattr(membership, "add_whitelist_entry", boom)

    response = await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/whitelist",
        data={"enabled": "1"},
    )

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# POST /servers/{name}/players/{uuid}/op
# ---------------------------------------------------------------------------


async def test_toggle_op_offline_adds_with_vanilla_defaults(client, fake_db, tmp_path):
    server = _server_row(tmp_path, state="exited")
    fake_db["servers"]["atm10"] = server
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    response = await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/op",
        data={"enabled": "1"},
    )

    assert response.status_code == 200
    raw = membership.ops_path(Path(server["dir"])).read_text()
    parsed = json.loads(raw)
    assert parsed == [
        {
            "uuid": _NOTCH_UUID,
            "name": "Notch",
            "level": 4,
            "bypassesPlayerLimit": False,
        }
    ]


async def test_toggle_op_running_uses_rcon_op_and_deop(
    client, fake_db, tmp_path, monkeypatch
):
    fake_db["servers"]["atm10"] = _server_row(tmp_path, state="running")
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    commands: list[str] = []

    async def fake_run(_docker, server, command):
        commands.append(command)
        return ""

    monkeypatch.setattr(server_rcon, "run_command", fake_run)

    await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/op", data={"enabled": "1"}
    )
    await client.post(
        f"/servers/atm10/players/{_NOTCH_UUID}/op", data={"enabled": "0"}
    )

    assert commands == ["op Notch", "deop Notch"]
