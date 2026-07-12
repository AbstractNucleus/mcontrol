"""Tests for the per-server Resources card route (slice 9 PR 1)."""

from pathlib import Path

import pytest

from mcontrol.infra import db, resources


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

    async def fake(_docker, container_name: str):
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
    assert "(67 %)" in body                     # memory percent. 8.097/12 ≈ 67.48 → 67
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
    # No CPU / memory percent figures. the OK template branch is not used.
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
            "variables": {},
            "scaffolded_at": None,
            "created_at": "2026-05-09T10:00:00Z",
            "updated_at": "2026-05-09T10:00:00Z",
        }
    )
    monkeypatch.setattr(db, "get_server", lambda n: server if n == "atm10" else None)

    body = (await client.get("/servers/atm10")).text

    # Order: lifecycle-row → server-resources mount → console pane.
    lifecycle_idx = body.index('class="lifecycle-row"')
    resources_idx = body.index('id="server-resources"')
    console_idx = body.index('class="console-pane"')
    assert lifecycle_idx < resources_idx < console_idx
    assert 'hx-get="/servers/atm10/resources"' in body


# ---------------------------------------------------------------------------
# State reconciliation via the 5s poll (OOB pill + buttons healing)
# ---------------------------------------------------------------------------


@pytest.fixture
def capture_state_writes(monkeypatch):
    seen: list[dict] = []

    def fake_update(**kwargs):
        seen.append(kwargs)

    monkeypatch.setattr(db, "update_server_state", fake_update)
    return seen


async def test_no_divergence_emits_no_oob_fragments(
    client, fake_db, fake_stats, capture_state_writes, tmp_path
):
    row = _row(tmp_path)
    fake_db["servers"]["atm10"] = row
    fake_stats["override"] = {
        "status": "ok",
        "cpu_percent": 1.0,
        "mem_used": 1024**3,
        "mem_limit": 2 * 1024**3,
        "container_state": "running",
    }

    response = await client.get("/servers/atm10/resources")

    assert response.status_code == 200
    assert "hx-swap-oob" not in response.text
    assert capture_state_writes == []


async def test_crashed_container_heals_pill_and_buttons(
    client, fake_db, fake_stats, capture_state_writes, tmp_path
):
    row = _row(tmp_path)  # DB says running
    fake_db["servers"]["atm10"] = row
    fake_stats["override"] = {"status": "not-running", "container_state": "exited"}

    response = await client.get("/servers/atm10/resources")

    body = response.text
    assert response.status_code == 200
    assert 'id="state-pill"' in body
    assert "state-pill--exited" in body
    assert 'hx-swap-oob="true"' in body
    assert 'id="lifecycle-buttons"' in body
    assert capture_state_writes == [{"name": "atm10", "state": "exited"}]


async def test_starting_promotes_to_running_once_port_bound(
    client, fake_db, fake_stats, capture_state_writes, tmp_path, monkeypatch
):
    from mcontrol.services import lifecycle_service

    row = _row(tmp_path)
    row["state"] = "starting"
    row["variables"] = {"port": 25565}
    fake_db["servers"]["atm10"] = row
    fake_stats["override"] = {
        "status": "ok",
        "cpu_percent": 1.0,
        "mem_used": 1024**3,
        "mem_limit": 2 * 1024**3,
        "container_state": "running",
    }

    async def fake_probe(port):
        return True

    monkeypatch.setattr(lifecycle_service, "probe_listener_once", fake_probe)

    response = await client.get("/servers/atm10/resources")

    assert "state-pill--running" in response.text
    assert capture_state_writes == [{"name": "atm10", "state": "running"}]


async def test_starting_stays_starting_while_port_unbound(
    client, fake_db, fake_stats, capture_state_writes, tmp_path, monkeypatch
):
    from mcontrol.services import lifecycle_service

    row = _row(tmp_path)
    row["state"] = "starting"
    row["variables"] = {"port": 25565}
    fake_db["servers"]["atm10"] = row
    fake_stats["override"] = {
        "status": "ok",
        "cpu_percent": 1.0,
        "mem_used": 1024**3,
        "mem_limit": 2 * 1024**3,
        "container_state": "running",
    }

    async def fake_probe(port):
        return False

    monkeypatch.setattr(lifecycle_service, "probe_listener_once", fake_probe)

    response = await client.get("/servers/atm10/resources")

    assert "hx-swap-oob" not in response.text
    assert capture_state_writes == []


async def test_stale_exited_not_promoted_while_port_unbound(
    client, fake_db, fake_stats, capture_state_writes, tmp_path, monkeypatch
):
    """Poll landing mid-start: DB still holds the pre-start state while
    Docker already reports "running" but the listener isn't up. The
    reconciler must not stomp the start handler's upcoming commit."""
    from mcontrol.services import lifecycle_service

    row = _row(tmp_path)
    row["state"] = "exited"
    row["variables"] = {"port": 25565}
    fake_db["servers"]["atm10"] = row
    fake_stats["override"] = {
        "status": "ok",
        "cpu_percent": 1.0,
        "mem_used": 1024**3,
        "mem_limit": 2 * 1024**3,
        "container_state": "running",
    }

    async def fake_probe(port):
        return False

    monkeypatch.setattr(lifecycle_service, "probe_listener_once", fake_probe)

    response = await client.get("/servers/atm10/resources")

    assert "hx-swap-oob" not in response.text
    assert capture_state_writes == []


async def test_unreachable_daemon_never_reconciles(
    client, fake_db, fake_stats, capture_state_writes, tmp_path
):
    row = _row(tmp_path)
    fake_db["servers"]["atm10"] = row
    fake_stats["override"] = {"status": "unreachable"}

    response = await client.get("/servers/atm10/resources")

    assert response.status_code == 200
    assert "hx-swap-oob" not in response.text
    assert capture_state_writes == []
