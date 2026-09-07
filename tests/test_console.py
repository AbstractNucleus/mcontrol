import asyncio
from pathlib import Path

import aiodocker
import pytest

from mcontrol.infra import rcon
from mcontrol.routes import console


@pytest.fixture(autouse=True)
def _clear_console_state():
    console._active_connections.clear()
    console._subscribers.clear()
    yield
    console._active_connections.clear()
    console._subscribers.clear()


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict] = {}
    from mcontrol.infra import db
    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    return rows


@pytest.fixture
def fake_docker_network(monkeypatch):
    from mcontrol.infra import docker_client

    attaches: list[str] = []
    detaches: list[str] = []

    async def fake_find(_docker, name):
        return f"{name}_default"

    async def fake_attach(_docker, network):
        attaches.append(network)

    async def fake_detach(_docker, network):
        detaches.append(network)

    monkeypatch.setattr(docker_client, "find_network_name", fake_find)
    monkeypatch.setattr(docker_client, "attach_self_to_network", fake_attach)
    monkeypatch.setattr(docker_client, "detach_self_from_network", fake_detach)

    return {"attaches": attaches, "detaches": detaches}


class _FakeRconConnection:
    def __init__(self):
        self.commands: list[str] = []
        self.closed = False
        self.fail_with: Exception | None = None

    async def run(self, command: str) -> str:
        self.commands.append(command)
        if self.fail_with is not None:
            exc, self.fail_with = self.fail_with, None
            raise exc
        return f"ack: {command}"

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_rcon(monkeypatch):
    """Stub rcon.connect. ``failures`` are raised (in order) before a
    connection is handed out; ``conns`` collects every connection made."""
    captured: dict = {"connects": 0, "failures": [], "conns": []}

    async def fake_connect(host, port, password):
        captured["connects"] += 1
        if captured["failures"]:
            raise captured["failures"].pop(0)
        conn = _FakeRconConnection()
        captured["conns"].append(conn)
        captured["conn"] = conn
        captured["host"] = host
        captured["port"] = port
        captured["password"] = password
        return conn

    monkeypatch.setattr(rcon, "connect", fake_connect)
    return captured


class _Request:
    def __init__(self, disconnected: bool = False):
        self.disconnected = disconnected

    async def is_disconnected(self):
        return self.disconnected


def _write_props(server_dir: Path, *, enable_rcon: bool, password: str) -> None:
    """Write a minimal server.properties under <server_dir>/server/."""
    props_dir = server_dir / "server"
    props_dir.mkdir(parents=True, exist_ok=True)
    (props_dir / "server.properties").write_text(
        f"enable-rcon={'true' if enable_rcon else 'false'}\n"
        f"rcon.port=25575\n"
        f"rcon.password={password}\n"
    )


async def _collect(gen) -> bytes:
    chunks: list[bytes] = []
    async for chunk in gen:
        chunks.append(chunk)
    return b"".join(chunks)


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
    _write_props(tmp_path, enable_rcon=True, password="hunter2")

    body = await _collect(
        console._stream(_Request(disconnected=True), object(), "atm10", "atm10", tmp_path)
    )

    assert b"rcon connected" in body
    assert fake_docker_network["attaches"] == ["atm10_default"]
    assert fake_docker_network["detaches"] == ["atm10_default"]
    assert fake_rcon["password"] == "hunter2"
    # Last subscriber out closes the shared connection and forgets it.
    assert fake_rcon["conn"].closed
    assert "atm10" not in console._active_connections
    assert not console._subscribers["atm10"]


async def test_stream_yields_friendly_message_when_rcon_disabled(
    fake_docker_network, fake_rcon, tmp_path
):
    _write_props(tmp_path, enable_rcon=False, password="hunter2")

    body = await _collect(console._stream(_Request(), object(), "atm10", "atm10", tmp_path))

    assert b"RCON is not enabled" in body
    assert body.endswith(console._CLOSED)
    # Network must not be touched when RCON is disabled.
    assert fake_docker_network["attaches"] == []
    assert fake_docker_network["detaches"] == []


async def test_stream_yields_friendly_message_when_password_empty(
    fake_docker_network, fake_rcon, tmp_path
):
    _write_props(tmp_path, enable_rcon=True, password="")

    body = await _collect(console._stream(_Request(), object(), "atm10", "atm10", tmp_path))

    assert b"RCON is not enabled" in body
    assert fake_docker_network["attaches"] == []


async def test_stream_yields_friendly_message_when_properties_missing(
    fake_docker_network, fake_rcon, tmp_path
):
    # No server.properties at all.
    body = await _collect(console._stream(_Request(), object(), "atm10", "atm10", tmp_path))

    assert b"RCON is not enabled" in body
    assert fake_docker_network["attaches"] == []


async def test_stream_reports_docker_error_and_closes(
    fake_docker_network, fake_rcon, tmp_path, monkeypatch
):
    """A missing container (never started) used to escape as a traceback and
    an EventSource reconnect loop; it must be a legible terminal message."""
    from mcontrol.infra import docker_client

    async def missing(_docker, _name):
        raise aiodocker.DockerError(404, "No such container: atm10")

    monkeypatch.setattr(docker_client, "find_network_name", missing)
    _write_props(tmp_path, enable_rcon=True, password="hunter2")

    body = await _collect(console._stream(_Request(), object(), "atm10", "atm10", tmp_path))

    assert b"[error] docker: No such container: atm10" in body
    assert body.endswith(console._CLOSED)
    assert fake_docker_network["attaches"] == []
    assert fake_rcon["connects"] == 0


async def test_stream_reports_auth_failure_and_closes(
    fake_docker_network, fake_rcon, tmp_path
):
    _write_props(tmp_path, enable_rcon=True, password="hunter2")
    fake_rcon["failures"].append(rcon.AuthenticationError("RCON authentication failed"))

    body = await _collect(console._stream(_Request(), object(), "atm10", "atm10", tmp_path))

    assert b"authentication failed" in body
    assert body.endswith(console._CLOSED)
    assert fake_rcon["connects"] == 1
    assert fake_docker_network["detaches"] == ["atm10_default"]


async def test_stream_retries_until_rcon_is_reachable(
    fake_docker_network, fake_rcon, tmp_path, monkeypatch
):
    """Stopped or still-booting server: announce once, keep retrying while
    the page is open, connect when RCON comes up."""
    monkeypatch.setattr(console, "_RETRY_INTERVAL_S", 0.01)
    _write_props(tmp_path, enable_rcon=True, password="hunter2")
    fake_rcon["failures"].extend([ConnectionRefusedError(), ConnectionRefusedError()])
    request = _Request()

    gen = console._stream(request, object(), "atm10", "atm10", tmp_path)
    async with asyncio.timeout(5):
        first = await gen.__anext__()
        assert b"RCON unreachable (connection refused" in first
        second = await gen.__anext__()
        assert second == console._KEEPALIVE  # second failed attempt stays quiet
        third = await gen.__anext__()
        assert b"rcon connected" in third
        request.disconnected = True
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    assert fake_rcon["connects"] == 3
    assert fake_docker_network["attaches"] == ["atm10_default"]
    assert fake_docker_network["detaches"] == ["atm10_default"]


async def test_stream_shares_one_connection_between_subscribers(
    fake_docker_network, fake_rcon, tmp_path
):
    """A second tab (or a reload racing the old stream's teardown) joins the
    live connection instead of being refused; both see every command."""
    _write_props(tmp_path, enable_rcon=True, password="hunter2")

    gen1 = console._stream(_Request(), object(), "atm10", "atm10", tmp_path)
    gen2 = console._stream(_Request(), object(), "atm10", "atm10", tmp_path)
    async with asyncio.timeout(5):
        assert b"rcon connected" in await gen1.__anext__()
        assert b"rcon connected" in await gen2.__anext__()
        assert fake_rcon["connects"] == 1
        assert len(console._subscribers["atm10"]) == 2

        assert await console.run_on_active("atm10", "list") == "ack: list"
        for gen in (gen1, gen2):
            assert b"&gt; list" in await gen.__anext__()
            assert b"ack: list" in await gen.__anext__()

        await gen1.aclose()
        assert not fake_rcon["conn"].closed
        assert console._active_connections["atm10"] is fake_rcon["conn"]

        await gen2.aclose()
        assert fake_rcon["conn"].closed
        assert "atm10" not in console._active_connections

    assert fake_docker_network["attaches"] == ["atm10_default"] * 2
    assert fake_docker_network["detaches"] == ["atm10_default"] * 2


async def test_dead_connection_is_dropped_and_streams_reconnect(
    fake_docker_network, fake_rcon, tmp_path, monkeypatch
):
    monkeypatch.setattr(console, "_RETRY_INTERVAL_S", 0.01)
    _write_props(tmp_path, enable_rcon=True, password="hunter2")
    request = _Request()

    gen = console._stream(request, object(), "atm10", "atm10", tmp_path)
    async with asyncio.timeout(5):
        assert b"rcon connected" in await gen.__anext__()
        first_conn = fake_rcon["conn"]
        first_conn.fail_with = rcon.RconClosedError("connection closed by peer")

        with pytest.raises(rcon.RconClosedError):
            await console.run_on_active("atm10", "list")
        assert first_conn.closed
        assert "atm10" not in console._active_connections

        assert b"&gt; list" in await gen.__anext__()
        assert b"rcon connection lost; reconnecting" in await gen.__anext__()
        assert b"rcon connected" in await gen.__anext__()
        assert fake_rcon["connects"] == 2
        assert console._active_connections["atm10"] is fake_rcon["conn"]
        assert await console.run_on_active("atm10", "seed") == "ack: seed"

        request.disconnected = True
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()


async def test_rcon_post_finds_active_session_and_runs_command(
    client, fake_get_server, fake_docker_network, fake_rcon, tmp_path
):
    """Once the SSE stream has populated _active_connections, POST should
    run the command and return 204."""
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
    }

    fake_conn = _FakeRconConnection()
    fake_queue: asyncio.Queue = asyncio.Queue()
    console._active_connections["atm10"] = fake_conn
    console._subscribers["atm10"].add(fake_queue)

    response = await client.post("/servers/atm10/rcon", data={"command": "list"})

    assert response.status_code == 204
    assert fake_conn.commands == ["list"]
    # Command echo + response landed on the SSE output queue.
    queued: list[str] = []
    while not fake_queue.empty():
        queued.append(fake_queue.get_nowait())
    assert queued == ["> list", "ack: list"]


async def test_rcon_post_returns_409_when_no_open_session(
    client, fake_get_server, fake_docker_network, fake_rcon, tmp_path
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
    }
    response = await client.post("/servers/atm10/rcon", data={"command": "list"})
    assert response.status_code == 409
    assert "not connected" in response.json()["detail"]


async def test_rcon_post_returns_409_and_tells_streams_when_socket_died(
    client, fake_get_server, fake_docker_network, fake_rcon, tmp_path
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
    }
    fake_conn = _FakeRconConnection()
    fake_conn.fail_with = rcon.RconClosedError("connection closed by peer")
    fake_queue: asyncio.Queue = asyncio.Queue()
    console._active_connections["atm10"] = fake_conn
    console._subscribers["atm10"].add(fake_queue)

    response = await client.post("/servers/atm10/rcon", data={"command": "list"})

    assert response.status_code == 409
    assert "reconnecting" in response.json()["detail"]
    assert "atm10" not in console._active_connections
    assert fake_queue.get_nowait() == "> list"
    assert fake_queue.get_nowait() is console._CONNECTION_LOST


async def test_rcon_post_returns_504_on_timeout(
    client, fake_get_server, fake_docker_network, fake_rcon, tmp_path
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
    }
    fake_conn = _FakeRconConnection()
    fake_conn.fail_with = TimeoutError()
    console._active_connections["atm10"] = fake_conn

    response = await client.post("/servers/atm10/rcon", data={"command": "list"})

    assert response.status_code == 504
    assert "atm10" not in console._active_connections


def test_read_rcon_properties_parses_enabled_and_password(tmp_path):
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
    props = tmp_path / "server.properties"
    props.write_text("enable-rcon=false\nrcon.password=hunter2\n")

    enabled, password = console._read_rcon_properties(props)
    assert enabled is False
    assert password == "hunter2"


def test_read_rcon_properties_returns_empty_password_when_blank(tmp_path):
    props = tmp_path / "server.properties"
    props.write_text("enable-rcon=true\nrcon.password=\n")

    assert console._read_rcon_properties(props) == (True, "")


def test_read_rcon_properties_returns_defaults_when_file_missing(tmp_path):
    assert console._read_rcon_properties(tmp_path / "nope.properties") == (False, "")
