import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def bindings_client(monkeypatch, tmp_path, fake_docker_factory):
    """Like the shared ``client`` fixture but with SERVER_BASE_PATH pointed
    at the per-test tmp_path, so the POST dir-containment validation can be
    exercised against real directories."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    from mcontrol.main import create_app

    app = create_app()
    app.state.docker = fake_docker_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, tmp_path


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


async def test_bindings_post_persists_overrides(bindings_client, fake_db):
    client, base = bindings_client
    target = base / "atm10-moved"
    target.mkdir()
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(base / "atm10"),
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "atm10-prod", "dir": str(target)},
    )

    assert response.status_code == 200
    assert fake_db["updates"] == [{
        "name": "atm10",
        "container_name": "atm10-prod",
        "dir": str(target),
    }]
    # Returns the read-only card with the new values.
    assert "atm10-prod" in response.text
    assert "atm10-moved" in response.text


async def test_bindings_post_clears_container_name_when_empty(bindings_client, fake_db):
    client, base = bindings_client
    target = base / "atm10"
    target.mkdir()
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": str(target),
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "", "dir": str(target)},
    )

    assert response.status_code == 200
    assert fake_db["updates"] == [{
        "name": "atm10",
        "container_name": None,
        "dir": str(target),
    }]


async def test_bindings_post_rejects_dir_outside_base(bindings_client, fake_db):
    client, base = bindings_client
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(base / "atm10"),
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "", "dir": str(base / ".." / "escape")},
    )

    assert response.status_code == 422
    assert fake_db["updates"] == []
    # Form re-rendered with an inline error and the submitted value echoed.
    assert "Directory must be under" in response.text
    assert "bindings-form__error" in response.text
    assert "escape" in response.text


async def test_bindings_post_rejects_nonexistent_dir(bindings_client, fake_db):
    client, base = bindings_client
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(base / "atm10"),
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "", "dir": str(base / "nope")},
    )

    assert response.status_code == 422
    assert fake_db["updates"] == []
    assert "Directory does not exist" in response.text
    assert "bindings-form__error" in response.text
    assert "nope" in response.text
