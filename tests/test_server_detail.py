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


async def test_server_detail_legacy_row_has_no_variables_card_or_banner(
    client, fake_get_server
):
    """scaffolded_at=None → legacy: no Variables card and no health banner."""
    row = _row("atm10")
    row["scaffolded_at"] = None
    fake_get_server["atm10"] = row

    response = await client.get("/servers/atm10")
    body = response.text
    assert 'id="variables"' not in body
    assert "health-banner" not in body
    # Legacy still shows the inline kv-list of variables.
    assert "no variables set" in body or "kv-list" in body


async def test_server_detail_scaffolded_row_renders_variables_card(
    client, fake_get_server, tmp_path
):
    from mcontrol import scaffolding

    server_dir = tmp_path / "newshire"
    variables = {"memory_budget_gb": 8, "port": 25575, "server_jar": "paper.jar"}
    scaffolding.scaffold("newshire", variables, tmp_path)

    row = {
        "name": "newshire", "container_name": None, "dir": str(server_dir),
        "image_base": "eclipse-temurin:21-jre", "state": "created",
        "variables": variables, "rcon_password": None,
        "scaffolded_at": "2026-05-06T12:00:00+00:00",
        "created_at": "2026-05-06T11:00:00Z",
        "updated_at": "2026-05-06T12:00:00Z",
    }
    fake_get_server["newshire"] = row

    response = await client.get("/servers/newshire")
    body = response.text
    assert response.status_code == 200
    assert 'id="variables"' in body
    assert 'hx-get="/servers/newshire/variables?edit=1"' in body
    # No health banner when files are intact and variables are complete.
    assert "health-banner" not in body
    # Legacy inline `variables` row is suppressed for scaffolded rows.
    # (Card carries the canonical view; the kv-list would be redundant.)
    body_dl = body.split('class="server-detail"', 1)[1].split('</dl>', 1)[0]
    assert "kv-list" not in body_dl


async def test_server_detail_renders_health_banner_for_stuck_scaffolding(
    client, fake_get_server, tmp_path
):
    row = {
        "name": "newshire", "container_name": None, "dir": str(tmp_path / "newshire"),
        "image_base": None, "state": "scaffolding",
        "variables": {"memory_budget_gb": 8, "port": 25575, "server_jar": "paper.jar"},
        "rcon_password": None,
        "scaffolded_at": "2026-05-06T12:00:00+00:00",
        "created_at": "2026-05-06T11:00:00Z",
        "updated_at": "2026-05-06T12:00:00Z",
    }
    fake_get_server["newshire"] = row

    response = await client.get("/servers/newshire")
    body = response.text
    assert "health-banner" in body
    assert "stuck-scaffolding" in body
