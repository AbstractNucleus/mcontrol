import pytest


@pytest.fixture
def fake_db(monkeypatch):
    rows: dict[str, dict] = {}
    updates: list[dict] = []

    from mcontrol.infra import db

    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    monkeypatch.setattr(db, "update_bindings", lambda **kw: updates.append(kw))

    return {"rows": rows, "updates": updates}


async def test_bindings_card_returns_404_for_unknown_server(client, fake_db):
    response = await client.get("/servers/unknown/bindings")
    assert response.status_code == 404


async def test_bindings_card_renders_current_values(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10",
        "container_name": "atm10-prod",
        "dir": "/srv/atm10",
    }

    response = await client.get("/servers/atm10/bindings")

    assert response.status_code == 200
    assert "atm10-prod" in response.text
    assert "/srv/atm10" in response.text


async def test_bindings_form_renders_when_edit_query_param_set(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
    }

    response = await client.get("/servers/atm10/bindings?edit=1")

    assert response.status_code == 200
    assert 'name="container_name"' in response.text
    assert 'name="dir"' in response.text
    # Falls back placeholder when override is null.
    assert "/srv/atm10" in response.text


async def test_bindings_post_persists_overrides(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "atm10-prod", "dir": "/operator/edited/path"},
    )

    assert response.status_code == 200
    assert fake_db["updates"] == [{
        "name": "atm10",
        "container_name": "atm10-prod",
        "dir": "/operator/edited/path",
    }]
    # Returns the read-only card with the new values.
    assert "atm10-prod" in response.text
    assert "/operator/edited/path" in response.text


async def test_bindings_post_clears_container_name_when_empty(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": "/srv/atm10",
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "", "dir": "/srv/atm10"},
    )

    assert response.status_code == 200
    assert fake_db["updates"] == [{
        "name": "atm10",
        "container_name": None,
        "dir": "/srv/atm10",
    }]
