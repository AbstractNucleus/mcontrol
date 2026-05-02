import pytest


@pytest.fixture
def fake_server_row(monkeypatch):
    rows: dict[str, dict] = {}

    def fake_get(name):
        return rows.get(name)

    from mcontrol import db

    monkeypatch.setattr(db, "get_server", fake_get)
    return rows


@pytest.fixture
def stub_db_writes(monkeypatch):
    seen: list[tuple[str, dict]] = []
    from mcontrol import db

    def cap(label):
        def fn(**kwargs):
            seen.append((label, kwargs))
        return fn

    monkeypatch.setattr(db, "set_rcon_password", cap("set_rcon_password"))
    monkeypatch.setattr(db, "update_server_state", cap("update_server_state"))
    return seen


@pytest.fixture
def stub_docker_and_compose(monkeypatch, tmp_path):
    from mcontrol import compose_runner, docker_client, env_writer, passwords

    started: list[str] = []
    stopped: list[str] = []
    restarted: list[str] = []
    composes: list[str] = []
    pwds: list[str] = []
    env_writes: list[tuple] = []

    async def fake_start(name): started.append(name)
    async def fake_stop(name): stopped.append(name)
    async def fake_restart(name): restarted.append(name)
    async def fake_up_force_recreate(server_dir): composes.append(str(server_dir))

    def fake_generate():
        pwds.append("PWD")
        return "PWD"

    def fake_write_rcon_password(path, pwd):
        env_writes.append((str(path), pwd))

    monkeypatch.setattr(docker_client, "start", fake_start)
    monkeypatch.setattr(docker_client, "stop", fake_stop)
    monkeypatch.setattr(docker_client, "restart", fake_restart)
    monkeypatch.setattr(compose_runner, "up_force_recreate", fake_up_force_recreate)
    monkeypatch.setattr(passwords, "generate", fake_generate)
    monkeypatch.setattr(env_writer, "write_rcon_password", fake_write_rcon_password)

    return {
        "started": started, "stopped": stopped, "restarted": restarted,
        "composes": composes, "pwds": pwds, "env_writes": env_writes,
    }


async def test_stop_calls_docker_stop_and_returns_state_pill(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running", "rcon_password": "OLD_PWD",
    }

    response = await client.post("/servers/atm10/lifecycle/stop")

    assert response.status_code == 200
    assert "exited" in response.text  # state-pill text
    assert stub_docker_and_compose["stopped"] == ["atm10"]
    assert ("update_server_state", {"name": "atm10", "state": "exited"}) in stub_db_writes


async def test_start_with_existing_password_uses_docker_start(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "exited", "rcon_password": "OLD_PWD",
    }
    (tmp_path / ".env").write_text("RCON_PASSWORD=OLD_PWD\n")

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert "running" in response.text
    assert stub_docker_and_compose["started"] == ["atm10"]
    assert stub_docker_and_compose["composes"] == []
    assert stub_docker_and_compose["pwds"] == []


async def test_start_generates_password_and_force_recreates_when_db_password_missing(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "exited", "rcon_password": None,
    }

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert stub_docker_and_compose["pwds"] == ["PWD"]
    assert ("set_rcon_password", {"name": "atm10", "password": "PWD"}) in stub_db_writes
    assert stub_docker_and_compose["env_writes"] == [(str(tmp_path / ".env"), "PWD")]
    assert stub_docker_and_compose["started"] == []
    assert stub_docker_and_compose["composes"] == [str(tmp_path)]


async def test_start_force_recreates_when_disk_env_diverges_from_db(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "exited", "rcon_password": "DB_PWD",
    }
    (tmp_path / ".env").write_text("RCON_PASSWORD=ON_DISK_DIFFERENT\n")

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert stub_docker_and_compose["env_writes"] == [(str(tmp_path / ".env"), "DB_PWD")]
    assert stub_docker_and_compose["composes"] == [str(tmp_path)]
    assert stub_docker_and_compose["started"] == []


async def test_restart_calls_docker_restart_when_env_already_matches(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "running", "rcon_password": "DB_PWD",
    }
    (tmp_path / ".env").write_text("RCON_PASSWORD=DB_PWD\n")

    response = await client.post("/servers/atm10/lifecycle/restart")

    assert response.status_code == 200
    assert stub_docker_and_compose["restarted"] == ["atm10"]
    assert stub_docker_and_compose["composes"] == []


async def test_lifecycle_returns_404_for_unknown_server(
    client, fake_server_row, stub_docker_and_compose
):
    response = await client.post("/servers/unknown/lifecycle/start")
    assert response.status_code == 404


async def test_lifecycle_uses_container_name_override(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": str(tmp_path),
        "state": "running", "rcon_password": "DB_PWD",
    }
    (tmp_path / ".env").write_text("RCON_PASSWORD=DB_PWD\n")

    await client.post("/servers/atm10/lifecycle/stop")

    assert stub_docker_and_compose["stopped"] == ["atm10-prod"]
