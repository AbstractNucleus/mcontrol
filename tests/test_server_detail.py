import pytest


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict | None] = {}

    def fake(name):
        return rows.get(name)

    from mcontrol import db

    monkeypatch.setattr(db, "get_server", fake)
    return rows


async def test_server_detail_returns_404_when_unknown(client, fake_get_server):
    response = await client.get("/servers/does-not-exist")

    assert response.status_code == 404


async def test_server_detail_renders_known_server(client, fake_get_server):
    fake_get_server["atm10"] = {
        "name": "atm10",
        "dir": "/home/abstract/servers/minecraft/atm10",
        "image_base": "eclipse-temurin:21-jre",
        "state": "running",
        "variables": {"memory_budget_gb": 12, "port": 25565},
        "created_at": "2026-04-27T10:00:00Z",
        "updated_at": "2026-04-27T10:00:00Z",
    }

    response = await client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "/home/abstract/servers/minecraft/atm10" in body
    assert "eclipse-temurin:21-jre" in body
    assert "running" in body
    # variables are surfaced verbatim
    assert "memory_budget_gb" in body
    assert "25565" in body


async def test_server_detail_handles_null_image_base(client, fake_get_server):
    fake_get_server["fresh"] = {
        "name": "fresh",
        "dir": "/srv/fresh",
        "image_base": None,
        "state": "unknown",
        "variables": {},
        "created_at": "2026-04-27T10:00:00Z",
        "updated_at": "2026-04-27T10:00:00Z",
    }

    response = await client.get("/servers/fresh")

    assert response.status_code == 200
    # Null image_base renders as the em-dash placeholder, not the literal "None".
    assert "—" in response.text
    assert ">None<" not in response.text
    assert "fresh" in response.text


async def test_server_detail_links_back_to_home(client, fake_get_server):
    fake_get_server["atm10"] = {
        "name": "atm10",
        "dir": "/srv/atm10",
        "image_base": None,
        "state": "running",
        "variables": {},
        "created_at": "2026-04-27T10:00:00Z",
        "updated_at": "2026-04-27T10:00:00Z",
    }

    response = await client.get("/servers/atm10")

    assert 'href="/"' in response.text
