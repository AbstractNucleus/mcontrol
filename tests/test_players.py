"""Tests for the central Players page (slice 7 PR 3)."""

import json
from pathlib import Path

import pytest

from mcontrol import db, membership, mojang

_NOTCH_UUID = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
_HEROBRINE_UUID = "ec561538-f3fd-461d-aff5-086b22154bce"


def _server_dir(tmp_path: Path, name: str) -> Path:
    server_dir = tmp_path / name
    (server_dir / "server").mkdir(parents=True, exist_ok=True)
    return server_dir


def _server_row(tmp_path: Path, name: str) -> dict:
    return {
        "name": name,
        "container_name": None,
        "dir": str(_server_dir(tmp_path, name)),
        "state": "exited",
        "scaffolded_at": None,
        "variables": {},
    }


@pytest.fixture
def fake_db(monkeypatch):
    """Substitute db.* helpers used by routes/players.py with a small
    in-memory store the test pokes directly."""
    state = {
        "servers": [],
        "players": [],
        "inserted_bulk": [],
        "inserted": [],
    }

    def list_servers():
        return list(state["servers"])

    def list_players():
        return list(state["players"])

    def get_player(uuid):
        for p in state["players"]:
            if p["uuid"] == uuid:
                return p
        return None

    def insert_player(*, uuid, name):
        row = {"uuid": uuid, "name": name}
        state["players"].append(row)
        state["inserted"].append(row)

    def insert_players_bulk(rows):
        for row in rows:
            state["players"].append(row)
        state["inserted_bulk"].append(list(rows))

    def upsert_player_from_mojang(*, uuid, name):
        for p in state["players"]:
            if p["uuid"] == uuid:
                prev = p["name"]
                if prev != name:
                    p["name"] = name
                return {"created": False, "previous_name": prev}
        state["players"].append({"uuid": uuid, "name": name})
        return {"created": True, "previous_name": None}

    monkeypatch.setattr(db, "list_servers", list_servers)
    monkeypatch.setattr(db, "list_players", list_players)
    monkeypatch.setattr(db, "get_player", get_player)
    monkeypatch.setattr(db, "insert_player", insert_player)
    monkeypatch.setattr(db, "insert_players_bulk", insert_players_bulk)
    monkeypatch.setattr(db, "upsert_player_from_mojang", upsert_player_from_mojang)
    return state


# ---------------------------------------------------------------------------
# GET /players
# ---------------------------------------------------------------------------


async def test_get_renders_empty_roster(client, fake_db):
    response = await client.get("/players")
    assert response.status_code == 200
    body = response.text
    assert "Roster is empty" in body


async def test_get_renders_per_row_summary(client, fake_db, tmp_path):
    fake_db["players"] = [
        {"uuid": _NOTCH_UUID, "name": "Notch"},
        {"uuid": _HEROBRINE_UUID, "name": "Herobrine"},
    ]
    atm = _server_row(tmp_path, "atm10")
    moni = _server_row(tmp_path, "monifactory")
    fake_db["servers"] = [atm, moni]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(Path(moni["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(
        Path(moni["dir"]), uuid=_HEROBRINE_UUID, name="Herobrine"
    )

    body = (await client.get("/players")).text

    # Notch's row mentions both servers in whitelist + atm10 in op.
    assert "Notch" in body
    assert "Herobrine" in body
    # Server links go to /servers/{name}.
    assert 'href="/servers/atm10"' in body
    assert 'href="/servers/monifactory"' in body


async def test_get_renders_whitelist_disabled_indicator(client, fake_db, tmp_path):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    fake_db["servers"] = [atm]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    (Path(atm["dir"]) / "server" / "server.properties").write_text(
        "white-list=false\n"
    )

    body = (await client.get("/players")).text

    assert "(whitelist disabled)" in body


async def test_get_does_not_show_indicator_when_white_list_true(
    client, fake_db, tmp_path
):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    fake_db["servers"] = [atm]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    (Path(atm["dir"]) / "server" / "server.properties").write_text(
        "white-list=true\n"
    )

    body = (await client.get("/players")).text

    assert "(whitelist disabled)" not in body


async def test_get_shows_import_affordance_when_unknown_uuids_on_disk(
    client, fake_db, tmp_path
):
    atm = _server_row(tmp_path, "atm10")
    fake_db["servers"] = [atm]
    fake_db["players"] = []  # roster empty
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")

    body = (await client.get("/players")).text

    assert "1 membership(s) on disk for unknown UUID(s)" in body
    assert 'hx-post="/players/import"' in body


async def test_get_hides_import_affordance_when_count_is_zero(
    client, fake_db, tmp_path
):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    fake_db["servers"] = [atm]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")

    body = (await client.get("/players")).text

    assert "membership(s) on disk for unknown UUID(s)" not in body


# ---------------------------------------------------------------------------
# POST /players (Mojang lookup + upsert)
# ---------------------------------------------------------------------------


async def test_post_returns_422_on_invalid_name_shape(client, fake_db, monkeypatch):
    called = {"n": 0}

    async def fake_lookup(name):
        called["n"] += 1
        return {"uuid": _NOTCH_UUID, "name": name}

    monkeypatch.setattr(mojang, "lookup_by_name", fake_lookup)

    response = await client.post("/players", data={"name": "ab"})

    assert response.status_code == 422
    assert "letters, digits, and underscores" in response.text
    assert called["n"] == 0  # never reached Mojang


async def test_post_inserts_new_player_on_200(client, fake_db, monkeypatch):
    async def fake_lookup(name):
        return {"uuid": _NOTCH_UUID, "name": "Notch"}

    monkeypatch.setattr(mojang, "lookup_by_name", fake_lookup)

    response = await client.post("/players", data={"name": "Notch"})

    assert response.status_code == 200
    assert "Added Notch to the roster." in response.text
    assert any(p["uuid"] == _NOTCH_UUID for p in fake_db["players"])


async def test_post_surfaces_already_in_roster_when_uuid_known_with_same_name(
    client, fake_db, monkeypatch
):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    async def fake_lookup(name):
        return {"uuid": _NOTCH_UUID, "name": "Notch"}

    monkeypatch.setattr(mojang, "lookup_by_name", fake_lookup)

    response = await client.post("/players", data={"name": "Notch"})

    assert response.status_code == 200
    assert "Notch is already in the roster." in response.text
    assert "(was: " not in response.text


async def test_post_surfaces_was_old_name_when_mojang_returns_renamed_account(
    client, fake_db, monkeypatch
):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "OldNotch"}]

    async def fake_lookup(name):
        return {"uuid": _NOTCH_UUID, "name": "Notch"}

    monkeypatch.setattr(mojang, "lookup_by_name", fake_lookup)

    response = await client.post("/players", data={"name": "Notch"})

    assert response.status_code == 200
    assert "Notch is already in the roster (was: OldNotch)." in response.text
    # Roster name was refreshed.
    assert fake_db["players"][0]["name"] == "Notch"


async def test_post_returns_422_on_mojang_204(client, fake_db, monkeypatch):
    async def fake_lookup(name):
        return None

    monkeypatch.setattr(mojang, "lookup_by_name", fake_lookup)

    response = await client.post("/players", data={"name": "doesnotexist"})

    assert response.status_code == 422
    assert "No Minecraft account with that name" in response.text


async def test_post_returns_502_on_mojang_error(client, fake_db, monkeypatch):
    async def fake_lookup(name):
        raise mojang.MojangError("upstream broken")

    monkeypatch.setattr(mojang, "lookup_by_name", fake_lookup)

    response = await client.post("/players", data={"name": "Notch"})

    assert response.status_code == 502
    assert "Mojang lookup failed; try again." in response.text


# ---------------------------------------------------------------------------
# POST /players/import
# ---------------------------------------------------------------------------


async def test_import_inserts_unknown_uuids_in_one_call(client, fake_db, tmp_path):
    atm = _server_row(tmp_path, "atm10")
    moni = _server_row(tmp_path, "monifactory")
    fake_db["servers"] = [atm, moni]
    fake_db["players"] = []
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(
        Path(moni["dir"]), uuid=_HEROBRINE_UUID, name="Herobrine"
    )

    response = await client.post("/players/import")

    assert response.status_code == 200
    assert "Imported 2 new player(s)" in response.text
    # One bulk call, not three (decision 027: one DB transaction).
    assert len(fake_db["inserted_bulk"]) == 1
    inserted_uuids = {r["uuid"] for r in fake_db["inserted_bulk"][0]}
    assert inserted_uuids == {_NOTCH_UUID, _HEROBRINE_UUID}


async def test_import_skips_uuids_already_in_roster(client, fake_db, tmp_path):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    fake_db["servers"] = [atm]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(
        Path(atm["dir"]), uuid=_HEROBRINE_UUID, name="Herobrine"
    )

    response = await client.post("/players/import")

    assert response.status_code == 200
    assert "Imported 1 new player(s)" in response.text
    bulk = fake_db["inserted_bulk"][0]
    assert {r["uuid"] for r in bulk} == {_HEROBRINE_UUID}


async def test_import_with_no_unknowns_is_a_noop_with_zero_flash(
    client, fake_db, tmp_path
):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    fake_db["servers"] = [atm]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")

    response = await client.post("/players/import")

    assert response.status_code == 200
    assert "Imported 0 new player(s)" in response.text
    assert fake_db["inserted_bulk"] == []  # never called for empty list


async def test_import_takes_first_encountered_name_for_a_given_uuid(
    client, fake_db, tmp_path
):
    """If the same UUID has different names on different servers (rare but
    possible after a Mojang rename), Import takes whichever name it
    encounters first while walking servers."""
    atm = _server_row(tmp_path, "atm10")
    moni = _server_row(tmp_path, "monifactory")
    fake_db["servers"] = [atm, moni]  # walked in this order
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    # Pretend monifactory caught the post-rename name.
    membership.whitelist_path(Path(moni["dir"])).write_text(
        json.dumps([{"uuid": _NOTCH_UUID, "name": "NotchPrime"}])
    )

    await client.post("/players/import")

    bulk = fake_db["inserted_bulk"][0]
    assert bulk == [{"uuid": _NOTCH_UUID, "name": "Notch"}]


# ---------------------------------------------------------------------------
# PR 4: cascade-remove modal + handler
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_db_with_delete(fake_db, monkeypatch):
    """Extend the basic fake_db with delete_player tracking."""
    deleted: list[str] = []

    def delete_player(uuid):
        fake_db["players"][:] = [p for p in fake_db["players"] if p["uuid"] != uuid]
        deleted.append(uuid)

    monkeypatch.setattr(db, "delete_player", delete_player)
    fake_db["deleted"] = deleted
    return fake_db


async def test_remove_modal_returns_404_when_uuid_unknown(
    client, fake_db_with_delete
):
    response = await client.get(f"/players/{_NOTCH_UUID}/remove")
    assert response.status_code == 404


async def test_remove_modal_returns_400_on_invalid_uuid(
    client, fake_db_with_delete
):
    response = await client.get("/players/not-a-uuid/remove")
    assert response.status_code == 400


async def test_remove_modal_lists_pre_scanned_memberships(
    client, fake_db_with_delete, tmp_path
):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    moni = _server_row(tmp_path, "monifactory")
    fake_db_with_delete["servers"] = [atm, moni]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(Path(moni["dir"]), uuid=_NOTCH_UUID, name="Notch")

    response = await client.get(f"/players/{_NOTCH_UUID}/remove")

    assert response.status_code == 200
    body = response.text
    assert "Remove Notch from roster?" in body
    assert "atm10" in body
    assert "monifactory" in body
    assert "(whitelist)" in body
    assert "(ops)" in body
    assert 'value="all"' in body  # "Remove from all servers" form is shown


async def test_remove_modal_hides_remove_all_when_no_memberships(
    client, fake_db_with_delete, tmp_path
):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    fake_db_with_delete["servers"] = [_server_row(tmp_path, "atm10")]

    response = await client.get(f"/players/{_NOTCH_UUID}/remove")

    assert response.status_code == 200
    body = response.text
    assert "is not on any server" in body
    assert 'value="all"' not in body
    assert 'value="roster"' in body  # "Roster only" still rendered


async def test_post_scope_roster_deletes_row_only(
    client, fake_db_with_delete, tmp_path
):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    fake_db_with_delete["servers"] = [atm]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")

    response = await client.post(
        f"/players/{_NOTCH_UUID}/remove", data={"scope": "roster"}
    )

    assert response.status_code == 200
    assert _NOTCH_UUID in fake_db_with_delete["deleted"]
    # Disk untouched.
    entries, _ = membership.read_whitelist(Path(atm["dir"]))
    assert entries == [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    assert "On-disk memberships were not touched" in response.text


async def test_post_scope_all_offline_runs_per_server_remove_then_deletes(
    client, fake_db_with_delete, tmp_path
):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    moni = _server_row(tmp_path, "monifactory")
    fake_db_with_delete["servers"] = [atm, moni]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(Path(moni["dir"]), uuid=_NOTCH_UUID, name="Notch")

    response = await client.post(
        f"/players/{_NOTCH_UUID}/remove", data={"scope": "all"}
    )

    assert response.status_code == 200
    assert _NOTCH_UUID in fake_db_with_delete["deleted"]
    # Disk cleaned.
    assert membership.read_whitelist(Path(atm["dir"]))[0] == []
    assert membership.read_ops(Path(atm["dir"]))[0] == []
    assert membership.read_whitelist(Path(moni["dir"]))[0] == []
    body = response.text
    assert "Removed Notch from atm10 (whitelist)" in body
    assert "atm10 (ops)" in body
    assert "monifactory (whitelist)" in body


async def test_post_scope_all_running_uses_rcon(
    client, fake_db_with_delete, tmp_path, monkeypatch
):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    atm["state"] = "running"
    fake_db_with_delete["servers"] = [atm]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")

    from mcontrol import server_rcon

    commands: list[str] = []

    async def fake_run(_docker, server, command):
        commands.append(command)
        return ""

    monkeypatch.setattr(server_rcon, "run_command", fake_run)

    response = await client.post(
        f"/players/{_NOTCH_UUID}/remove", data={"scope": "all"}
    )

    assert response.status_code == 200
    assert sorted(commands) == ["deop Notch", "whitelist remove Notch"]
    # Disk on a running server is owned by the JVM — RCON path leaves it
    # to the server to update.
    assert _NOTCH_UUID in fake_db_with_delete["deleted"]


async def test_post_scope_all_partial_failure_surfaces_in_flash(
    client, fake_db_with_delete, tmp_path, monkeypatch
):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    atm = _server_row(tmp_path, "atm10")
    moni = _server_row(tmp_path, "monifactory")
    fake_db_with_delete["servers"] = [atm, moni]
    membership.add_whitelist_entry(Path(atm["dir"]), uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(Path(moni["dir"]), uuid=_NOTCH_UUID, name="Notch")

    # Stub remove on monifactory to raise.
    real_remove = membership.remove_whitelist_entry

    def selective_remove(server_dir, *, uuid):
        if str(server_dir) == moni["dir"]:
            raise membership.StaleWriteError("simulated drift")
        return real_remove(server_dir, uuid=uuid)

    monkeypatch.setattr(
        membership, "remove_whitelist_entry", selective_remove
    )

    response = await client.post(
        f"/players/{_NOTCH_UUID}/remove", data={"scope": "all"}
    )

    assert response.status_code == 200
    body = response.text
    assert "Removed Notch from atm10 (whitelist)." in body
    assert "Remove Notch from monifactory (whitelist) failed" in body
    # Per decision 027, the row is still hard-deleted; partial state
    # surfaces as an unknown-UUID affordance on the next page render.
    assert _NOTCH_UUID in fake_db_with_delete["deleted"]


async def test_post_scope_all_with_no_memberships_says_so(
    client, fake_db_with_delete, tmp_path
):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    fake_db_with_delete["servers"] = [_server_row(tmp_path, "atm10")]

    response = await client.post(
        f"/players/{_NOTCH_UUID}/remove", data={"scope": "all"}
    )

    assert response.status_code == 200
    assert "had no memberships on disk" in response.text
    assert _NOTCH_UUID in fake_db_with_delete["deleted"]


async def test_post_returns_400_on_invalid_scope(client, fake_db_with_delete):
    fake_db_with_delete["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]

    response = await client.post(
        f"/players/{_NOTCH_UUID}/remove", data={"scope": "wat"}
    )

    assert response.status_code == 400


async def test_post_returns_404_when_uuid_unknown(client, fake_db_with_delete):
    response = await client.post(
        f"/players/{_NOTCH_UUID}/remove", data={"scope": "roster"}
    )
    assert response.status_code == 404


async def test_get_renders_remove_link_in_each_row(client, fake_db, tmp_path):
    fake_db["players"] = [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    fake_db["servers"] = []

    body = (await client.get("/players")).text

    assert f'hx-get="/players/{_NOTCH_UUID}/remove"' in body
    assert 'hx-target="#player-modal"' in body
