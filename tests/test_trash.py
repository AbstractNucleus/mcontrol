"""Route tests for /trash (slice 11)."""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def trash_client(monkeypatch, tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, Path]]:
    """Test client whose SERVER_BASE_PATH is the per-test tmp_path."""
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    from mcontrol.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, tmp_path


def _make_tombstone(base: Path, name: str, ts: int, contents: bytes = b"x" * 1024) -> Path:
    tomb = base / f".deleted-{name}-{ts}"
    tomb.mkdir()
    (tomb / "world.dat").write_bytes(contents)
    return tomb


# ---------------------------------------------------------------------------
# GET /trash
# ---------------------------------------------------------------------------


async def test_get_trash_renders_empty_state_when_no_tombstones(trash_client):
    client, _base = trash_client
    response = await client.get("/trash")

    assert response.status_code == 200
    body = response.text
    assert "Trash" in body
    # Slice 12 reshaped the empty copy: "Trash is empty" / "Deleted
    # servers land here automatically." The "Deleted servers"
    # phrase is the stable signal — present in both old and new copy.
    assert "Trash is empty" in body
    assert "Deleted servers land here" in body


async def test_get_trash_lists_tombstones_with_age_and_bytes(trash_client):
    client, base = trash_client
    now = int(time.time())
    _make_tombstone(base, "atm10", now - 600, b"y" * 2048)

    response = await client.get("/trash")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "ago" in body
    # 2048 B → "2.0 KiB" via format_bytes
    assert "2.0 KiB" in body


async def test_get_trash_button_disabled_when_no_sweepable_tombstones(trash_client):
    client, base = trash_client
    now = int(time.time())
    _make_tombstone(base, "fresh", now - 600, b"x")  # 10 min old

    response = await client.get("/trash")

    body = response.text
    assert "disabled" in body
    assert "nothing older than 7 days" in body


async def test_get_trash_button_enabled_when_sweepable_tombstones_exist(trash_client):
    client, base = trash_client
    now = int(time.time())
    _make_tombstone(base, "stale", now - 8 * 86400, b"x" * 1024)

    response = await client.get("/trash")

    body = response.text
    assert "Empty trash — 1 tombstone" in body
    assert "older than 7 days" in body


async def test_get_trash_includes_topnav(trash_client):
    client, _base = trash_client
    response = await client.get("/trash")
    body = response.text
    assert 'href="/trash"' in body
    assert 'href="/players"' in body
    assert 'href="/"' in body


# ---------------------------------------------------------------------------
# GET /trash/empty/confirm + GET /trash/{name}/confirm
# ---------------------------------------------------------------------------


async def test_get_empty_confirm_lists_only_old_enough(trash_client):
    client, base = trash_client
    now = int(time.time())
    _make_tombstone(base, "stale", now - 8 * 86400)
    _make_tombstone(base, "fresh", now - 600)

    response = await client.get("/trash/empty/confirm")

    assert response.status_code == 200
    body = response.text
    assert "stale" in body
    assert "fresh" not in body
    assert "EMPTY" in body  # the confirm phrase


async def test_get_delete_confirm_returns_404_for_non_tombstone(trash_client):
    client, _base = trash_client
    response = await client.get("/trash/not-a-tombstone/confirm")
    assert response.status_code == 404


async def test_get_delete_confirm_renders_for_valid_tombstone_name(trash_client):
    client, _base = trash_client
    response = await client.get("/trash/.deleted-atm10-1700000000/confirm")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body  # the parsed original name
    assert "Type" in body
    assert "confirm_name" in body


# ---------------------------------------------------------------------------
# POST /trash/empty
# ---------------------------------------------------------------------------


async def test_post_empty_purges_only_tombstones_older_than_seven_days(trash_client):
    client, base = trash_client
    now = int(time.time())
    stale = _make_tombstone(base, "stale", now - 8 * 86400)
    fresh = _make_tombstone(base, "fresh", now - 600)

    response = await client.post("/trash/empty", data={"confirm": "EMPTY"})

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/trash"
    assert not stale.exists()
    assert fresh.exists()


async def test_post_empty_rejects_when_confirm_text_wrong(trash_client):
    client, base = trash_client
    now = int(time.time())
    stale = _make_tombstone(base, "stale", now - 8 * 86400)

    response = await client.post("/trash/empty", data={"confirm": "empty"})

    assert response.status_code == 422
    assert stale.exists()


async def test_post_empty_rejects_when_confirm_missing(trash_client):
    client, base = trash_client
    now = int(time.time())
    stale = _make_tombstone(base, "stale", now - 8 * 86400)

    response = await client.post("/trash/empty", data={})

    assert response.status_code == 422
    assert stale.exists()


# ---------------------------------------------------------------------------
# POST /trash/{name}/delete
# ---------------------------------------------------------------------------


async def test_post_delete_removes_the_named_tombstone(trash_client):
    client, base = trash_client
    now = int(time.time())
    tomb = _make_tombstone(base, "atm10", now - 60)

    response = await client.post(
        f"/trash/{tomb.name}/delete", data={"confirm_name": "atm10"}
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/trash"
    assert not tomb.exists()


async def test_post_delete_rejects_when_confirm_name_mismatched(trash_client):
    client, base = trash_client
    now = int(time.time())
    tomb = _make_tombstone(base, "atm10", now - 60)

    response = await client.post(
        f"/trash/{tomb.name}/delete", data={"confirm_name": "wrongname"}
    )

    assert response.status_code == 422
    assert tomb.exists()


async def test_post_delete_returns_404_for_non_tombstone_dir_name(trash_client):
    client, _base = trash_client
    response = await client.post(
        "/trash/not-a-tombstone/delete", data={"confirm_name": "anything"}
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        ".deleted-AB-1700000000",        # uppercase in slug
        ".deleted-foo_bar-1700000000",   # underscore not allowed
        ".deleted-foo-bar",              # ts not digits
    ],
)
async def test_post_delete_rejects_malformed_tombstone_names(trash_client, payload: str):
    client, _base = trash_client
    response = await client.post(
        f"/trash/{payload}/delete", data={"confirm_name": "foo"}
    )
    assert response.status_code == 404
