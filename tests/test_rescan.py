"""Tests for the operator-triggered discovery endpoint (decision 034)."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Override the conftest env fixture so SERVER_BASE_PATH points at a
    real, existing tmp dir. The rescan route 503s on a missing path; for
    happy-path tests we want it to exist."""
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))


@pytest.fixture
def fake_servers(monkeypatch):
    rows: list[dict] = []
    from mcontrol import db
    monkeypatch.setattr(db, "list_servers", lambda: rows)
    return rows


@pytest.fixture
def fake_stats(monkeypatch):
    async def fake_read(_docker, container_name: str):
        return {"status": "unreachable"}
    from mcontrol import resources
    monkeypatch.setattr(resources, "read_container_stats", fake_read)


@pytest.fixture
def stub_discovery(monkeypatch):
    from pathlib import Path

    from mcontrol import discovery

    seen: list[Path] = []

    async def fake_run(_docker, base_path: Path) -> int:
        seen.append(base_path)
        return 0

    monkeypatch.setattr(discovery, "run_discovery", fake_run)
    return seen


async def test_rescan_htmx_returns_204_with_hx_refresh(client, stub_discovery):
    response = await client.post("/rescan", headers={"HX-Request": "true"})

    assert response.status_code == 204
    assert response.headers.get("HX-Refresh") == "true"
    assert len(stub_discovery) == 1


async def test_rescan_non_htmx_redirects_to_home(client, stub_discovery):
    response = await client.post("/rescan")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert len(stub_discovery) == 1


async def test_rescan_503_when_base_path_missing(monkeypatch, tmp_path) -> None:
    """If SERVER_BASE_PATH doesn't exist, the operator-triggered route
    surfaces 503 (the startup lifespan handler logs-and-continues for
    the same condition, but at request time the operator deserves the
    failure to be visible)."""
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path / "does-not-exist"))

    from mcontrol.main import create_app
    from tests.conftest import make_fake_docker

    app = create_app()
    # ASGITransport skips lifespan, so seed app.state.docker for the
    # Depends(get_docker) on /rescan (#98).
    app.state.docker = make_fake_docker()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/rescan", headers={"HX-Request": "true"})

    assert response.status_code == 503
    assert "does not exist" in response.text


async def test_home_page_renders_rescan_button(client, fake_servers, fake_stats):
    response = await client.get("/")

    assert response.status_code == 200
    assert 'hx-post="/rescan"' in response.text
    assert "Rescan" in response.text


async def test_home_empty_state_mentions_rescan_not_restart(
    client, fake_servers, fake_stats
):
    """Empty-state copy should point operators at Rescan, not 'restart
    the panel' (the pre-slice-14 instruction)."""
    response = await client.get("/")
    body = response.text

    assert "No servers yet" in body
    assert "restart the panel" not in body
    assert "Rescan" in body
