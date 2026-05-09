"""Tests for the per-server Resources card route (slice 9 PR 1)."""

from pathlib import Path

import pytest

from mcontrol import db, resources


def _row(tmp_path: Path, *, name: str = "atm10", container_name: str | None = None) -> dict:
    server_dir = tmp_path / name
    (server_dir / "server").mkdir(parents=True, exist_ok=True)
    return {
        "name": name,
        "container_name": container_name,
        "dir": str(server_dir),
        "state": "running",
    }


@pytest.fixture
def fake_db(monkeypatch):
    state: dict = {"servers": {}}
    monkeypatch.setattr(db, "get_server", lambda n: state["servers"].get(n))
    return state


@pytest.fixture
def fake_stats(monkeypatch):
    """Captures the container_name passed in and returns a configurable
    stats dict (matching the resources.read_container_stats contract)."""
    captured: dict = {"container_name": None}
    payload: dict = {
        "status": "ok",
        "cpu_percent": 12.4,
        "mem_used": 8 * 1024**3 + 100 * 1024**2,  # 8.1 GiB
        "mem_limit": 12 * 1024**3,  # 12.0 GiB
    }

    async def fake(container_name: str):
        captured["container_name"] = container_name
        return captured.get("override", payload)

    monkeypatch.setattr(resources, "read_container_stats", fake)
    return captured


# ---------------------------------------------------------------------------
# 404 / routing
# ---------------------------------------------------------------------------


async def test_returns_404_when_server_unknown(client, fake_db, fake_stats):
    response = await client.get("/servers/nope/resources")
    assert response.status_code == 404


async def test_resolves_container_via_db_helper_when_override_set(
    client, fake_db, fake_stats, tmp_path
):
    fake_db["servers"]["atm10"] = _row(tmp_path, container_name="renamed-atm10")

    await client.get("/servers/atm10/resources")

    assert fake_stats["container_name"] == "renamed-atm10"


async def test_falls_back_to_name_when_no_container_override(
    client, fake_db, fake_stats, tmp_path
):
    fake_db["servers"]["atm10"] = _row(tmp_path, container_name=None)

    await client.get("/servers/atm10/resources")

    assert fake_stats["container_name"] == "atm10"


# ---------------------------------------------------------------------------
# OK render
# ---------------------------------------------------------------------------


async def test_ok_render_shows_cpu_memory_disk(client, fake_db, fake_stats, tmp_path):
    server = _row(tmp_path)
    fake_db["servers"]["atm10"] = server
    # 4 KiB of disk content.
    (Path(server["dir"]) / "server" / "world.dat").write_bytes(b"x" * 4096)

    response = await client.get("/servers/atm10/resources")

    assert response.status_code == 200
    body = response.text
    assert "12.4 %" in body                    # CPU
    assert "8.1 GiB / 12.0 GiB" in body         # memory used / limit
    assert "(67 %)" in body                     # memory percent — 8.097/12 ≈ 67.48 → 67
    assert "4.0 KiB" in body                    # disk
    assert "every 5 s" in body                  # ok caption


async def test_ok_render_includes_polling_attributes_for_continued_swap(
    client, fake_db, fake_stats, tmp_path
):
    fake_db["servers"]["atm10"] = _row(tmp_path)

    body = (await client.get("/servers/atm10/resources")).text

    assert 'id="server-resources"' in body
    assert 'hx-get="/servers/atm10/resources"' in body
    assert 'hx-trigger="load, every 5s"' in body
    assert 'hx-swap="outerHTML"' in body


# ---------------------------------------------------------------------------
# not-running fallback
# ---------------------------------------------------------------------------


async def test_not_running_dashes_container_numbers_but_keeps_disk(
    client, fake_db, fake_stats, tmp_path
):
    server = _row(tmp_path)
    fake_db["servers"]["atm10"] = server
    (Path(server["dir"]) / "server" / "world.dat").write_bytes(b"y" * 1024)
    fake_stats["override"] = {"status": "not-running"}

    response = await client.get("/servers/atm10/resources")
    body = response.text

    assert response.status_code == 200
    # CPU and memory show em-dashes; disk still renders the real number.
    assert "container not running" in body
    assert "1.0 KiB" in body
    # No CPU / memory percent figures — the OK template branch is not used.
    assert "%" not in body.split("Disk")[0]


# ---------------------------------------------------------------------------
# unreachable fallback
# ---------------------------------------------------------------------------


async def test_unreachable_uses_distinct_caption(
    client, fake_db, fake_stats, tmp_path
):
    fake_db["servers"]["atm10"] = _row(tmp_path)
    fake_stats["override"] = {"status": "unreachable"}

    body = (await client.get("/servers/atm10/resources")).text

    assert "Docker daemon unreachable" in body
    assert "container not running" not in body


async def test_unreachable_still_renders_disk(client, fake_db, fake_stats, tmp_path):
    server = _row(tmp_path)
    fake_db["servers"]["atm10"] = server
    (Path(server["dir"]) / "server" / "world.dat").write_bytes(b"z" * 2048)
    fake_stats["override"] = {"status": "unreachable"}

    body = (await client.get("/servers/atm10/resources")).text

    assert "2.0 KiB" in body


# ---------------------------------------------------------------------------
# Mount on detail page
# ---------------------------------------------------------------------------


async def test_detail_page_mounts_resources_card_above_metadata(
    client, monkeypatch, tmp_path
):
    """The card sits between the lifecycle row and the <dl> metadata so
    live status sits with lifecycle controls in one diagnostic cluster."""
    server = _row(tmp_path)
    server.update(
        {
            "image_base": "eclipse-temurin:21-jre",
            "variables": {},
            "rcon_password": None,
            "scaffolded_at": None,
            "created_at": "2026-05-09T10:00:00Z",
            "updated_at": "2026-05-09T10:00:00Z",
        }
    )
    monkeypatch.setattr(db, "get_server", lambda n: server if n == "atm10" else None)

    body = (await client.get("/servers/atm10")).text

    # Order: lifecycle-row → server-resources mount → server-detail dl.
    lifecycle_idx = body.index('class="lifecycle-row"')
    resources_idx = body.index('id="server-resources"')
    detail_dl_idx = body.index('class="server-detail"')
    assert lifecycle_idx < resources_idx < detail_dl_idx
    assert 'hx-get="/servers/atm10/resources"' in body
