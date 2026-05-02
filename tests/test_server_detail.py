import pytest


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict | None] = {}

    from mcontrol import db
    monkeypatch.setattr(db, "get_server", rows.get)
    return rows


def _row(
    name: str,
    *,
    image_base: str | None = "eclipse-temurin:21-jre",
    state: str = "running",
) -> dict:
    return {
        "name": name,
        "container_name": None,
        "dir": f"/srv/{name}",
        "image_base": image_base,
        "state": state,
        "variables": {},
        "rcon_password": None,
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    }


async def test_server_detail_returns_404_when_unknown(client, fake_get_server):
    response = await client.get("/servers/does-not-exist")

    assert response.status_code == 404


async def test_server_detail_renders_known_server(client, fake_get_server):
    fake_get_server["atm10"] = {
        "name": "atm10",
        "container_name": None,
        "dir": "/home/abstract/servers/minecraft/atm10",
        "image_base": "eclipse-temurin:21-jre",
        "state": "running",
        "variables": {"memory_budget_gb": 12, "port": 25565},
        "rcon_password": "set",
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    }

    response = await client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "/home/abstract/servers/minecraft/atm10" in body
    assert "eclipse-temurin:21-jre" in body
    assert "running" in body
    assert "memory_budget_gb" in body
    assert "25565" in body


async def test_server_detail_renders_lifecycle_buttons(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'hx-post="/servers/atm10/lifecycle/start"' in body
    assert 'hx-post="/servers/atm10/lifecycle/stop"' in body
    assert 'hx-post="/servers/atm10/lifecycle/restart"' in body


async def test_server_detail_renders_log_pane(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    assert 'sse-connect="/servers/atm10/logs"' in response.text


async def test_server_detail_renders_console_pane(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'sse-connect="/servers/atm10/rcon"' in body
    assert 'hx-post="/servers/atm10/rcon"' in body


async def test_server_detail_renders_bindings_card(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert "Bindings" in body
    assert 'hx-get="/servers/atm10/bindings?edit=1"' in body


async def test_server_detail_handles_null_image_base(client, fake_get_server):
    fake_get_server["fresh"] = _row("fresh", image_base=None, state="unknown")

    response = await client.get("/servers/fresh")

    assert response.status_code == 200
    # Null image_base renders as the em-dash placeholder, not the literal "None".
    assert "—" in response.text
    assert ">None<" not in response.text
    assert "fresh" in response.text


async def test_server_detail_links_back_to_home(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    assert 'href="/"' in response.text
