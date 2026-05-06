"""Tests for routes/delete_server.py — type-name confirm + tombstone.

Decision 026: Delete renames <dir> to <base>/.deleted-<name>-<ts>/ and
deletes the row. Refuses when state='running'. Type-name confirm is
the destructive-op friction that mirrors slice 5's recursive-delete.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def base_dir(tmp_path, monkeypatch, env):
    """Override SERVER_BASE_PATH to a per-test tmp_path; tests put each
    server's dir under it so the tombstone lands in the same parent."""
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
async def app_client(base_dir) -> AsyncIterator[AsyncClient]:
    from mcontrol.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def fake_db(monkeypatch):
    state = {"rows": [], "deletes": []}
    from mcontrol import db

    def fake_get_server(name):
        for row in state["rows"]:
            if row["name"] == name:
                return row
        return None

    def fake_delete_server(name):
        state["deletes"].append(name)
        state["rows"][:] = [r for r in state["rows"] if r["name"] != name]

    monkeypatch.setattr(db, "get_server", fake_get_server)
    monkeypatch.setattr(db, "delete_server", fake_delete_server)
    return state


def _row(base_dir: Path, *, name: str = "newshire", state: str = "exited") -> dict:
    server_dir = base_dir / name
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "marker.txt").write_text("server data")
    return {
        "name": name,
        "container_name": None,
        "dir": str(server_dir),
        "state": state,
        "scaffolded_at": "2026-05-06T12:00:00+00:00",
        "variables": {},
    }


# ---- GET ----------------------------------------------------------


async def test_get_returns_button_when_state_is_exited(
    app_client, fake_db, base_dir
):
    fake_db["rows"].append(_row(base_dir))

    response = await app_client.get("/servers/newshire/delete")

    assert response.status_code == 200
    body = response.text
    assert "Delete server" in body
    # Button leads to the confirm form.
    assert 'hx-get="/servers/newshire/delete?confirm=1"' in body
    # No type-name input yet.
    assert 'name="confirm_name"' not in body


async def test_get_button_disabled_when_state_running(
    app_client, fake_db, base_dir
):
    fake_db["rows"].append(_row(base_dir, state="running"))

    response = await app_client.get("/servers/newshire/delete")

    assert response.status_code == 200
    body = response.text
    assert "disabled" in body
    # No HTMX wire-up on a disabled button.
    assert 'hx-get="/servers/newshire/delete?confirm=1"' not in body
    assert "Stop the server" in body


async def test_get_confirm_returns_form_with_typename_input(
    app_client, fake_db, base_dir
):
    fake_db["rows"].append(_row(base_dir))

    response = await app_client.get("/servers/newshire/delete?confirm=1")

    assert response.status_code == 200
    body = response.text
    assert 'name="confirm_name"' in body
    assert 'hx-post="/servers/newshire/delete"' in body
    # Cancel returns to the button state.
    assert 'hx-get="/servers/newshire/delete"' in body


async def test_get_returns_404_for_unknown(app_client, fake_db):
    response = await app_client.get("/servers/unknown/delete")
    assert response.status_code == 404


# ---- POST ---------------------------------------------------------


async def test_post_tombstones_dir_and_deletes_row(
    app_client, fake_db, base_dir
):
    fake_db["rows"].append(_row(base_dir))
    server_dir = base_dir / "newshire"
    assert server_dir.exists()

    response = await app_client.post(
        "/servers/newshire/delete",
        data={"confirm_name": "newshire"},
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/"

    # DB row is gone.
    assert fake_db["deletes"] == ["newshire"]

    # Original dir gone, replaced by a single .deleted-newshire-<ts>/ tombstone.
    assert not server_dir.exists()
    tombstones = [p for p in base_dir.iterdir() if p.name.startswith(".deleted-newshire-")]
    assert len(tombstones) == 1
    # Files preserved inside the tombstone — recovery is `mv tombstone newshire`.
    assert (tombstones[0] / "marker.txt").read_text() == "server data"


async def test_post_refuses_when_state_running(app_client, fake_db, base_dir):
    fake_db["rows"].append(_row(base_dir, state="running"))
    server_dir = base_dir / "newshire"

    response = await app_client.post(
        "/servers/newshire/delete",
        data={"confirm_name": "newshire"},
    )

    assert response.status_code == 409
    assert fake_db["deletes"] == []
    # Files untouched.
    assert server_dir.exists()
    assert (server_dir / "marker.txt").exists()


async def test_post_rejects_when_confirm_name_does_not_match(
    app_client, fake_db, base_dir
):
    fake_db["rows"].append(_row(base_dir))

    response = await app_client.post(
        "/servers/newshire/delete",
        data={"confirm_name": "wrong"},
    )

    assert response.status_code == 422
    body = response.text
    assert "exactly to confirm" in body
    # Re-rendered form preserves what they typed.
    assert 'value="wrong"' in body
    assert fake_db["deletes"] == []
    assert (base_dir / "newshire").exists()


async def test_post_rejects_when_confirm_name_empty(
    app_client, fake_db, base_dir
):
    fake_db["rows"].append(_row(base_dir))

    response = await app_client.post(
        "/servers/newshire/delete",
        data={"confirm_name": ""},
    )

    assert response.status_code == 422
    assert fake_db["deletes"] == []


async def test_post_returns_404_for_unknown(app_client, fake_db):
    response = await app_client.post(
        "/servers/unknown/delete",
        data={"confirm_name": "unknown"},
    )
    assert response.status_code == 404


async def test_post_succeeds_when_dir_already_missing(
    app_client, fake_db, base_dir
):
    """If the dir was hand-deleted before mcontrol got the request, the
    DB row should still be removed cleanly. Nothing to tombstone."""
    row = _row(base_dir)
    import shutil

    shutil.rmtree(row["dir"])
    fake_db["rows"].append(row)

    response = await app_client.post(
        "/servers/newshire/delete",
        data={"confirm_name": "newshire"},
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/"
    assert fake_db["deletes"] == ["newshire"]


# ---- Detail page wires the partial in -------------------------------


async def test_detail_page_includes_delete_zone(app_client, fake_db, base_dir):
    fake_db["rows"].append(_row(base_dir))

    response = await app_client.get("/servers/newshire")

    assert response.status_code == 200
    body = response.text
    assert 'id="delete-zone"' in body
    assert "Delete server" in body
