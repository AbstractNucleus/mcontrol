"""Tests for routes/new_server.py — the /servers/new form + POST flow.

DB and the scaffolding module are mocked at the boundary; tests drive
real disk under tmp_path so the rollback path can rmtree real files.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def base_dir(tmp_path, monkeypatch, env):
    """Override SERVER_BASE_PATH to a per-test tmp_path. Depends on `env`
    so the override always applies after the defaults are loaded."""
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
async def app_client(base_dir) -> AsyncIterator[AsyncClient]:
    from mcontrol.main import create_app
    from tests.conftest import make_fake_docker

    app = create_app()
    # ASGITransport doesn't trigger lifespan, so seed app.state.docker
    # for the Depends(get_docker) the home route resolves (#98).
    app.state.docker = make_fake_docker()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def fake_db(monkeypatch):
    """In-memory stand-in for the bits of `db` the route touches."""
    state = {
        "rows": [],  # list of {name, dir, state, variables, ...}
        "writes": [],  # ordered tuples of (op, kwargs) for assertions
        "raise_on_mark": False,
    }

    from mcontrol import db

    def fake_list_servers():
        return list(state["rows"])

    def fake_get_server(name):
        for row in state["rows"]:
            if row["name"] == name:
                return row
        return None

    def fake_insert_scaffolding_server(*, name, dir, variables):
        state["writes"].append(("insert", {"name": name, "dir": dir, "variables": variables}))
        state["rows"].append(
            {"name": name, "dir": dir, "state": "scaffolding", "variables": variables,
             "container_name": None, "scaffolded_at": None}
        )

    def fake_mark_scaffolded(*, name):
        state["writes"].append(("mark", {"name": name}))
        if state["raise_on_mark"]:
            raise RuntimeError("simulated DB failure on mark")
        for row in state["rows"]:
            if row["name"] == name:
                row["state"] = "created"
                row["scaffolded_at"] = "2026-05-06T12:00:00+00:00"

    def fake_delete_server(name):
        state["writes"].append(("delete", {"name": name}))
        state["rows"][:] = [r for r in state["rows"] if r["name"] != name]

    monkeypatch.setattr(db, "list_servers", fake_list_servers)
    monkeypatch.setattr(db, "get_server", fake_get_server)
    monkeypatch.setattr(db, "insert_scaffolding_server", fake_insert_scaffolding_server)
    monkeypatch.setattr(db, "mark_scaffolded", fake_mark_scaffolded)
    monkeypatch.setattr(db, "delete_server", fake_delete_server)

    return state


def _form(**overrides) -> dict:
    """A minimum-valid POST body."""
    body = {
        "name": "newshire",
        "memory_budget_gb": "8",
        "port": "25575",
        "server_jar": "paper-1.21.4.jar",
        "jvm_extra_args": "",
        "accept_eula": "on",
    }
    body.update({k: str(v) for k, v in overrides.items()})
    return body


# ---- GET /servers/new -----------------------------------------------


async def test_get_new_renders_form(app_client, fake_db):
    response = await app_client.get("/servers/new")

    assert response.status_code == 200
    body = response.text
    assert 'name="name"' in body
    assert 'name="memory_budget_gb"' in body
    assert 'name="port"' in body
    assert 'name="server_jar"' in body
    assert 'name="jvm_extra_args"' in body
    assert 'name="accept_eula"' in body
    # Hint about uploading the jar after scaffolding (slice 6 contract).
    assert "upload" in body.lower()


async def test_home_links_to_new_server_form(app_client, fake_db):
    response = await app_client.get("/")
    assert response.status_code == 200
    assert 'href="/servers/new"' in response.text


# ---- POST happy path ------------------------------------------------


async def test_post_happy_path_scaffolds_and_redirects(
    app_client, base_dir, fake_db
):
    response = await app_client.post("/servers/new", data=_form())

    assert response.status_code == 303
    assert response.headers["location"] == "/servers/newshire"

    # DB writes happened in the prescribed order: insert → mark.
    ops = [op for op, _ in fake_db["writes"]]
    assert ops == ["insert", "mark"]

    insert_kwargs = fake_db["writes"][0][1]
    assert insert_kwargs["name"] == "newshire"
    assert insert_kwargs["dir"] == str((base_dir / "newshire").resolve())
    assert insert_kwargs["variables"] == {
        "memory_budget_gb": 8,
        "port": 25575,
        "server_jar": "paper-1.21.4.jar",
    }

    # Files landed on disk via the real scaffolding module.
    compose = base_dir / "newshire" / "docker-compose.yml"
    start = base_dir / "newshire" / "server" / "start_server.sh"
    eula = base_dir / "newshire" / "server" / "eula.txt"
    assert compose.exists()
    assert start.exists()
    assert eula.exists()
    assert "container_name: newshire" in compose.read_text()
    assert "-Xmx6g" in start.read_text()
    assert "eula=true" in eula.read_text()


async def test_post_includes_jvm_extra_args_in_variables_when_present(
    app_client, base_dir, fake_db
):
    response = await app_client.post(
        "/servers/new",
        data=_form(jvm_extra_args="-XX:+UseG1GC"),
    )

    assert response.status_code == 303
    insert_kwargs = fake_db["writes"][0][1]
    assert insert_kwargs["variables"]["jvm_extra_args"] == "-XX:+UseG1GC"


# ---- POST validation errors ----------------------------------------


@pytest.mark.parametrize(
    "field,value,fragment",
    [
        ("name", "Bad-Name", "lowercase"),
        ("name", "ab", "32 chars"),  # too short (< 3 after first letter)
        ("name", "1abc", "must start with a letter"),
        ("memory_budget_gb", "1", "Minimum"),
        ("port", "80", "between"),
        ("port", "70000", "between"),
        ("server_jar", "   ", "Required"),
    ],
)
async def test_post_rejects_invalid_field(
    app_client, fake_db, field, value, fragment
):
    response = await app_client.post("/servers/new", data=_form(**{field: value}))

    assert response.status_code == 422
    assert fragment.lower() in response.text.lower()
    assert fake_db["writes"] == []  # nothing reached the DB


async def test_post_rejects_when_eula_not_accepted(app_client, fake_db):
    body = _form()
    del body["accept_eula"]  # simulate unchecked checkbox (field absent from form data)

    response = await app_client.post("/servers/new", data=body)

    assert response.status_code == 422
    assert "eula" in response.text.lower()
    assert fake_db["writes"] == []


async def test_post_rejects_when_name_already_exists_in_db(app_client, fake_db):
    fake_db["rows"].append(
        {"name": "newshire", "dir": "/elsewhere", "state": "running", "variables": {}}
    )

    response = await app_client.post("/servers/new", data=_form())

    assert response.status_code == 422
    assert "already in use" in response.text
    assert fake_db["writes"] == []


async def test_post_rejects_when_directory_already_exists(
    app_client, base_dir, fake_db
):
    (base_dir / "newshire").mkdir()

    response = await app_client.post("/servers/new", data=_form())

    assert response.status_code == 422
    assert "Directory already exists" in response.text
    assert fake_db["writes"] == []


async def test_post_rejects_when_port_collides_with_other_server(
    app_client, fake_db
):
    fake_db["rows"].append(
        {"name": "atm10", "dir": "/srv/atm10", "state": "running",
         "variables": {"port": 25575}}
    )

    response = await app_client.post("/servers/new", data=_form(port=25575))

    assert response.status_code == 422
    body = response.text
    assert "25575" in body
    assert "atm10" in body
    assert fake_db["writes"] == []


# ---- POST rollback on mid-flight failure ---------------------------


async def test_post_rolls_back_disk_and_db_when_scaffold_raises(
    app_client, base_dir, fake_db, monkeypatch
):
    from mcontrol import scaffolding

    def boom(name, variables, base):
        # Make a partial mess so we can verify rmtree cleans it up.
        (base / name).mkdir(parents=True, exist_ok=True)
        (base / name / "half-written").write_text("oops")
        raise RuntimeError("simulated scaffold failure")

    monkeypatch.setattr(scaffolding, "scaffold", boom)

    response = await app_client.post("/servers/new", data=_form())

    assert response.status_code == 500
    # DB rollback ran: insert then delete; mark was not reached.
    ops = [op for op, _ in fake_db["writes"]]
    assert ops == ["insert", "delete"]
    # Disk rollback wiped the partial dir.
    assert not (base_dir / "newshire").exists()


async def test_post_rolls_back_when_mark_scaffolded_raises(
    app_client, base_dir, fake_db
):
    fake_db["raise_on_mark"] = True

    response = await app_client.post("/servers/new", data=_form())

    assert response.status_code == 500
    ops = [op for op, _ in fake_db["writes"]]
    assert ops == ["insert", "mark", "delete"]
    # Disk-side: scaffold ran successfully, so the dir + files exist —
    # rollback's rmtree must have cleared them.
    assert not (base_dir / "newshire").exists()
