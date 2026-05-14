from unittest.mock import AsyncMock, MagicMock

import pytest

from mcontrol import docker_client


class _FakeSummary:
    """Mimics aiodocker.DockerContainer with a populated `_container` dict
    (the /containers/json summary), which is what container_states_by_name
    now reads."""

    def __init__(self, name: str, status: str):
        self._container = {"Names": [f"/{name}"], "State": status}


def _docker_with_summaries(summaries: list[_FakeSummary]) -> MagicMock:
    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.list = AsyncMock(return_value=summaries)
    return docker


async def test_container_states_by_name_returns_mapping(env):
    docker = _docker_with_summaries([
        _FakeSummary("atm10", "running"),
        _FakeSummary("monifactory", "exited"),
    ])

    states = await docker_client.container_states_by_name(docker)

    docker.containers.list.assert_awaited_once_with(all=True)
    assert states == {"atm10": "running", "monifactory": "exited"}


async def test_container_states_strips_leading_slash(env):
    docker = _docker_with_summaries([_FakeSummary("kobra_kollektivet", "created")])

    states = await docker_client.container_states_by_name(docker)

    assert states == {"kobra_kollektivet": "created"}


async def test_container_states_returns_empty_when_list_raises(env):
    """Inner-branch failure: containers.list raises."""
    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.list = AsyncMock(side_effect=RuntimeError("kernel said no"))

    states = await docker_client.container_states_by_name(docker)

    assert states == {}


# --- Slice 4: lifecycle / logs / network helpers ----------------------------


class _FakeContainer:
    def __init__(self, name: str = "atm10", networks: dict | None = None):
        self.name = name
        self._started = False
        self._stopped = False
        self._restarted = False
        nets = networks if networks is not None else {"atm10_default": {}}
        self._show_data = {
            "Name": f"/{name}",
            "NetworkSettings": {"Networks": nets},
        }

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._stopped = True

    async def restart(self) -> None:
        self._restarted = True

    async def show(self) -> dict:
        return self._show_data

    async def log(self, *, stdout=True, stderr=True, tail="all", follow=False):
        for line in ["[INFO] starting", "[INFO] done"]:
            yield line


def _docker_with_container(container: _FakeContainer) -> MagicMock:
    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(return_value=container)
    return docker


async def test_start_calls_container_start(env):
    fake = _FakeContainer()
    docker = _docker_with_container(fake)

    await docker_client.start(docker, "atm10")

    assert fake._started is True


async def test_stop_calls_container_stop(env):
    fake = _FakeContainer()
    docker = _docker_with_container(fake)

    await docker_client.stop(docker, "atm10")

    assert fake._stopped is True


async def test_restart_calls_container_restart(env):
    fake = _FakeContainer()
    docker = _docker_with_container(fake)

    await docker_client.restart(docker, "atm10")

    assert fake._restarted is True


async def test_start_raises_timeout_when_container_hangs(env, monkeypatch):
    import asyncio

    class _HangingContainer(_FakeContainer):
        async def start(self):
            await asyncio.sleep(9999)

    docker = _docker_with_container(_HangingContainer())
    monkeypatch.setattr(docker_client, "_LIFECYCLE_TIMEOUT_S", 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await docker_client.start(docker, "atm10")


async def test_stop_raises_timeout_when_container_hangs(env, monkeypatch):
    import asyncio

    class _HangingContainer(_FakeContainer):
        async def stop(self):
            await asyncio.sleep(9999)

    docker = _docker_with_container(_HangingContainer())
    monkeypatch.setattr(docker_client, "_LIFECYCLE_TIMEOUT_S", 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await docker_client.stop(docker, "atm10")


async def test_restart_raises_timeout_when_container_hangs(env, monkeypatch):
    import asyncio

    class _HangingContainer(_FakeContainer):
        async def restart(self):
            await asyncio.sleep(9999)

    docker = _docker_with_container(_HangingContainer())
    monkeypatch.setattr(docker_client, "_LIFECYCLE_TIMEOUT_S", 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await docker_client.restart(docker, "atm10")


async def test_logs_stream_yields_lines(env):
    fake = _FakeContainer()

    async def fake_log_method(*, stdout, stderr, tail, follow):
        yield "boot line 1"
        yield "boot line 2"

    fake.log = fake_log_method
    docker = _docker_with_container(fake)

    lines = [line async for line in docker_client.logs_stream(docker, "atm10", tail=200)]

    assert lines == ["boot line 1", "boot line 2"]


async def test_find_network_name_returns_first_network(env):
    docker = _docker_with_container(
        _FakeContainer(networks={"atm10_default": {}, "host": {}})
    )

    name = await docker_client.find_network_name(docker, "atm10")

    assert name == "atm10_default"


async def test_find_network_name_returns_none_when_no_networks(env):
    docker = _docker_with_container(_FakeContainer(networks={}))

    name = await docker_client.find_network_name(docker, "atm10")

    assert name is None


def test_self_container_id_reads_hostname_env(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "abc123def456")

    assert docker_client.self_container_id() == "abc123def456"


async def test_attach_self_to_network_calls_connect(env, monkeypatch):
    connected: list[tuple[str, str]] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def connect(self, *, container):
            connected.append((self.name, container))

    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(side_effect=lambda name: _Network(name))
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")

    assert connected == [("atm10_default", "selfid")]


async def test_detach_self_from_network_calls_disconnect(env, monkeypatch):
    disconnected: list[tuple[str, str]] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def disconnect(self, *, container):
            disconnected.append((self.name, container))

    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(side_effect=lambda name: _Network(name))
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.detach_self_from_network(docker, "atm10_default")

    assert disconnected == [("atm10_default", "selfid")]
