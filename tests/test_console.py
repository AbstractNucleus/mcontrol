import asyncio
from pathlib import Path

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


def _write_props(server_dir: Path, *, enable_rcon: bool, password: str) -> None:
    """Write a minimal server.properties under <server_dir>/server/."""
    props_dir = server_dir / "server"
    props_dir.mkdir(parents=True, exist_ok=True)
    (props_dir / "server.properties").write_text(
        f"enable-rcon={'true' if enable_rcon else 'false'}\n"
        f"rcon.port=25575\n"
        f"rcon.password={password}\n"
    )


async def test_rcon_get_returns_404_for_unknown_server(
    client, fake_get_server, fake_docker_network
):
    response = await client.get("/servers/unknown/rcon")
    assert response.status_code == 404


async def test_stream_attaches_then_detaches_network(
    fake_docker_network, fake_rcon, tmp_path
):
    """Drive console._stream directly (bypassing httpx/ASGI) with a request
    that reports disconnected immediately. With a valid server.properties
    in place, the generator should attach the network on entry, yield the
    connected banner, observe disconnect, and detach on exit."""
    from mcontrol.routes import console

    _write_props(tmp_path, enable_rcon=True, password="hunter2")

    class _MockRequest:
        async def is_disconnected(self):
            return True

    gen = console._stream(_MockRequest(), "atm10", "atm10", tmp_path)
    chunks: list[bytes] = []
    async for chunk in gen:
        chunks.append(chunk)
    await gen.aclose()

    assert any(b"data:" in c for c in chunks)
    assert fake_docker_network["attaches"] == ["atm10_default"]
    assert fake_docker_network["detaches"] == ["atm10_default"]
    assert fake_rcon["password"] == "hunter2"


async def test_stream_yields_friendly_message_when_rcon_disabled(
    fake_docker_network, fake_rcon, tmp_path
):
    from mcontrol.routes import console

    _write_props(tmp_path, enable_rcon=False, password="hunter2")

    class _MockRequest:
        async def is_disconnected(self):
            return False

    chunks: list[bytes] = []
    async for chunk in console._stream(_MockRequest(), "atm10", "atm10", tmp_path):
        chunks.append(chunk)

    body = b"".join(chunks)
    assert b"RCON is not enabled" in body
    # Network must not be touched when RCON is disabled.
    assert fake_docker_network["attaches"] == []
    assert fake_docker_network["detaches"] == []


async def test_stream_yields_friendly_message_when_password_empty(
    fake_docker_network, fake_rcon, tmp_path
):
    from mcontrol.routes import console

    _write_props(tmp_path, enable_rcon=True, password="")

    class _MockRequest:
        async def is_disconnected(self):
            return False

    chunks: list[bytes] = []
    async for chunk in console._stream(_MockRequest(), "atm10", "atm10", tmp_path):
        chunks.append(chunk)

    body = b"".join(chunks)
    assert b"RCON is not enabled" in body
    assert fake_docker_network["attaches"] == []


async def test_stream_yields_friendly_message_when_properties_missing(
    fake_docker_network, fake_rcon, tmp_path
):
    from mcontrol.routes import console

    # No server.properties at all.

    class _MockRequest:
        async def is_disconnected(self):
            return False

    chunks: list[bytes] = []
    async for chunk in console._stream(_MockRequest(), "atm10", "atm10", tmp_path):
        chunks.append(chunk)

    body = b"".join(chunks)
    assert b"RCON is not enabled" in body
    assert fake_docker_network["attaches"] == []


async def test_rcon_post_finds_active_session_and_runs_command(
    client, fake_get_server, fake_docker_network, fake_rcon, tmp_path
):
    """Once the SSE stream has populated _active_connections, POST should
    run the command and return 204."""
    from mcontrol.routes import console

    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
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


async def test_rcon_post_returns_409_when_no_open_session(
    client, fake_get_server, fake_docker_network, fake_rcon, tmp_path
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
    }
    response = await client.post("/servers/atm10/rcon", data={"command": "list"})
    assert response.status_code == 409


async def test_stream_rejects_concurrent_connection(
    fake_docker_network, fake_rcon, tmp_path
):
    """A second SSE connect for the same server while one is already open must
    yield an error immediately and touch no network resources."""
    from mcontrol.routes import console

    _write_props(tmp_path, enable_rcon=True, password="hunter2")

    lock = console._connection_locks["concurrent_test"]
    await lock.acquire()
    try:
        class _MockRequest:
            async def is_disconnected(self):
                return False

        chunks: list[bytes] = []
        async for chunk in console._stream(
            _MockRequest(), "concurrent_test", "concurrent_test", tmp_path
        ):
            chunks.append(chunk)
    finally:
        lock.release()

    body = b"".join(chunks)
    assert b"already open" in body
    assert fake_docker_network["attaches"] == []
    assert "conn" not in fake_rcon


def test_read_rcon_properties_parses_enabled_and_password(tmp_path):
    from mcontrol.routes import console

    props = tmp_path / "server.properties"
    props.write_text(
        "#Minecraft server properties\n"
        "#Mon Jan 01 12:00:00 UTC 2026\n"
        "enable-rcon=true\n"
        "rcon.port=25575\n"
        "rcon.password=hunter2\n"
        "motd=Welcome\n"
    )

    assert console._read_rcon_properties(props) == (True, "hunter2")


def test_read_rcon_properties_returns_disabled_when_flag_false(tmp_path):
    from mcontrol.routes import console

    props = tmp_path / "server.properties"
    props.write_text("enable-rcon=false\nrcon.password=hunter2\n")

    enabled, password = console._read_rcon_properties(props)
    assert enabled is False
    assert password == "hunter2"


def test_read_rcon_properties_returns_empty_password_when_blank(tmp_path):
    from mcontrol.routes import console

    props = tmp_path / "server.properties"
    props.write_text("enable-rcon=true\nrcon.password=\n")

    assert console._read_rcon_properties(props) == (True, "")


def test_read_rcon_properties_returns_defaults_when_file_missing(tmp_path):
    from mcontrol.routes import console

    assert console._read_rcon_properties(tmp_path / "nope.properties") == (False, "")
