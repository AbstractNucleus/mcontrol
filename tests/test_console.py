import asyncio

import pytest


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict] = {}
    from mcontrol import db
    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    return rows


@pytest.fixture
def fake_docker_network(monkeypatch):
    from mcontrol import docker_client

    attaches: list[str] = []
    detaches: list[str] = []

    async def fake_find(name):
        return f"{name}_default"

    async def fake_attach(network):
        attaches.append(network)

    async def fake_detach(network):
        detaches.append(network)

    monkeypatch.setattr(docker_client, "find_network_name", fake_find)
    monkeypatch.setattr(docker_client, "attach_self_to_network", fake_attach)
    monkeypatch.setattr(docker_client, "detach_self_from_network", fake_detach)

    return {"attaches": attaches, "detaches": detaches}


class _FakeRconConnection:
    def __init__(self):
        self.commands: list[str] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def run(self, command: str) -> str:
        self.commands.append(command)
        return f"ack: {command}"

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_rcon(monkeypatch):
    captured: dict[str, _FakeRconConnection] = {}

    async def fake_connect(host, port, password):
        conn = _FakeRconConnection()
        captured["conn"] = conn
        captured["host"] = host
        captured["port"] = port
        captured["password"] = password
        return conn

    from mcontrol import rcon
    monkeypatch.setattr(rcon, "connect", fake_connect)
    return captured


async def test_rcon_get_returns_404_for_unknown_server(client, fake_get_server, fake_docker_network):
    response = await client.get("/servers/unknown/rcon")
    assert response.status_code == 404


async def test_stream_attaches_then_detaches_network(
    fake_docker_network, fake_rcon
):
    """Drive console._stream directly (bypassing httpx/ASGI) with a request
    that reports disconnected immediately. The generator should attach the
    network on entry, yield the connected banner, observe disconnect, and
    detach on exit through its finally blocks."""
    from mcontrol.routes import console

    class _MockRequest:
        async def is_disconnected(self):
            return True

    gen = console._stream(_MockRequest(), "atm10", "atm10", "hunter2")
    chunks: list[bytes] = []
    async for chunk in gen:
        chunks.append(chunk)
    await gen.aclose()

    assert any(b"data:" in c for c in chunks)
    assert fake_docker_network["attaches"] == ["atm10_default"]
    assert fake_docker_network["detaches"] == ["atm10_default"]


async def test_rcon_post_finds_active_session_and_runs_command(
    client, fake_get_server, fake_docker_network, fake_rcon
):
    """Once the SSE stream has populated _active_connections, POST should
    run the command and return 204."""
    from mcontrol.routes import console

    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "rcon_password": "hunter2",
    }

    fake_conn = _FakeRconConnection()
    fake_queue: asyncio.Queue = asyncio.Queue()
    console._active_connections["atm10"] = fake_conn
    console._output_queues["atm10"] = fake_queue
    try:
        response = await client.post("/servers/atm10/rcon", data={"command": "list"})
    finally:
        console._active_connections.pop("atm10", None)
        console._output_queues.pop("atm10", None)

    assert response.status_code == 204
    assert fake_conn.commands == ["list"]
    # Command echo + response landed on the SSE output queue.
    queued: list[str] = []
    while not fake_queue.empty():
        queued.append(fake_queue.get_nowait())
    assert "> list" in queued
    assert "ack: list" in queued


async def test_rcon_get_returns_424_when_password_missing(
    client, fake_get_server, fake_docker_network, fake_rcon
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "rcon_password": None,
    }
    response = await client.get("/servers/atm10/rcon")
    assert response.status_code == 424


async def test_rcon_post_returns_409_when_no_open_session(
    client, fake_get_server, fake_docker_network, fake_rcon
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "rcon_password": "hunter2",
    }
    response = await client.post("/servers/atm10/rcon", data={"command": "list"})
    assert response.status_code == 409
