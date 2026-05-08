import pytest


@pytest.fixture
def fake_servers(monkeypatch):
    rows: list[dict] = []

    def fake_list_servers():
        return rows

    from mcontrol import db

    monkeypatch.setattr(db, "list_servers", fake_list_servers)
    return rows


async def test_home_renders_wordmark(client, fake_servers):
    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "mcontrol" in body
    assert "/static/tokens.css" in body
    assert "/static/app.css" in body


async def test_home_shows_empty_state_when_no_servers(client, fake_servers):
    response = await client.get("/")

    assert response.status_code == 200
    assert "No servers yet" in response.text


async def test_home_lists_servers_when_present(client, fake_servers):
    fake_servers.append({"name": "atm10", "state": "running"})
    fake_servers.append({"name": "monifactory", "state": "exited"})

    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "monifactory" in body
    assert "running" in body
    assert "exited" in body
    assert "No servers yet" not in body


async def test_home_links_each_server_to_detail_page(client, fake_servers):
    fake_servers.append({"name": "atm10", "state": "running"})

    response = await client.get("/")

    assert response.status_code == 200
    assert 'href="/servers/atm10"' in response.text


async def test_home_links_to_central_players_page(client, fake_servers):
    response = await client.get("/")

    assert response.status_code == 200
    assert 'href="/players"' in response.text
