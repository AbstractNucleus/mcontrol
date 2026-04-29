from unittest.mock import AsyncMock, MagicMock

import pytest

from mcontrol import docker_client


class _FakeSummary:
    """Mimics aiodocker.DockerContainer with a populated `_container` dict
    (the /containers/json summary), which is what container_states_by_name
    now reads."""

    def __init__(self, name: str, status: str):
        self._container = {"Names": [f"/{name}"], "State": status}


class _FakeContainers:
    def __init__(self, containers: list[_FakeSummary]):
        self._containers = containers

    async def list(self, all: bool = False) -> list[_FakeSummary]:  # noqa: A002
        assert all is True, "discovery must list ALL containers, including stopped"
        return self._containers


class _FakeDocker:
    def __init__(self, containers: list[_FakeSummary]):
        self.containers = _FakeContainers(containers)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_docker(monkeypatch):
    containers: list[_FakeSummary] = []

    def factory(*, url: str | None = None) -> _FakeDocker:
        return _FakeDocker(containers)

    monkeypatch.setattr(docker_client.aiodocker, "Docker", factory)
    return containers


async def test_container_states_by_name_returns_mapping(env, fake_docker):
    fake_docker.append(_FakeSummary("atm10", "running"))
    fake_docker.append(_FakeSummary("monifactory", "exited"))

    states = await docker_client.container_states_by_name()

    assert states == {"atm10": "running", "monifactory": "exited"}


async def test_container_states_strips_leading_slash(env, fake_docker):
    fake_docker.append(_FakeSummary("kobra_kollektivet", "created"))

    states = await docker_client.container_states_by_name()

    assert states == {"kobra_kollektivet": "created"}


async def test_container_states_returns_empty_when_docker_constructor_fails(env, monkeypatch):
    class _Boom:
        def __init__(self, *_, **__):
            raise RuntimeError("docker daemon is sulking")

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Boom)

    states = await docker_client.container_states_by_name()

    assert states == {}


async def test_container_states_returns_empty_when_list_raises(env, monkeypatch):
    """Inner-branch failure: constructor succeeds but containers.list raises."""

    class _PartiallyBrokenDocker:
        def __init__(self, *_, **__):
            self.containers = MagicMock()
            self.containers.list = AsyncMock(side_effect=RuntimeError("kernel said no"))

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _PartiallyBrokenDocker)

    states = await docker_client.container_states_by_name()

    assert states == {}


async def test_container_states_closes_the_client(env, monkeypatch):
    closed_flag = {"closed": False}

    class _TrackingDocker:
        def __init__(self, *_, **__):
            self.containers = MagicMock()
            self.containers.list = AsyncMock(return_value=[])

        async def close(self):
            closed_flag["closed"] = True

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _TrackingDocker)

    await docker_client.container_states_by_name()

    assert closed_flag["closed"] is True


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


def _docker_with_named_container(monkeypatch, container: _FakeContainer):
    """Wire docker_client.aiodocker.Docker to return a fake whose
    .containers.get(name) yields the given container."""

    class _ContainersWithGet:
        async def get(self, name):  # noqa: ARG002
            return container

    class _Docker:
        def __init__(self, *_, **__):
            self.containers = _ContainersWithGet()

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Docker)
    return container


async def test_start_calls_container_start(env, monkeypatch):
    fake = _docker_with_named_container(monkeypatch, _FakeContainer())

    await docker_client.start("atm10")

    assert fake._started is True


async def test_stop_calls_container_stop(env, monkeypatch):
    fake = _docker_with_named_container(monkeypatch, _FakeContainer())

    await docker_client.stop("atm10")

    assert fake._stopped is True


async def test_restart_calls_container_restart(env, monkeypatch):
    fake = _docker_with_named_container(monkeypatch, _FakeContainer())

    await docker_client.restart("atm10")

    assert fake._restarted is True


async def test_logs_stream_yields_lines(env, monkeypatch):
    fake = _FakeContainer()

    async def fake_log_method(*, stdout, stderr, tail, follow):
        yield "boot line 1"
        yield "boot line 2"

    fake.log = fake_log_method
    _docker_with_named_container(monkeypatch, fake)

    lines = [line async for line in docker_client.logs_stream("atm10", tail=200)]

    assert lines == ["boot line 1", "boot line 2"]


async def test_find_network_name_returns_first_network(env, monkeypatch):
    _docker_with_named_container(
        monkeypatch,
        _FakeContainer(networks={"atm10_default": {}, "host": {}}),
    )

    name = await docker_client.find_network_name("atm10")

    assert name == "atm10_default"


async def test_find_network_name_returns_none_when_no_networks(env, monkeypatch):
    _docker_with_named_container(monkeypatch, _FakeContainer(networks={}))

    name = await docker_client.find_network_name("atm10")

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

    class _Networks:
        async def get(self, name):
            return _Network(name)

    class _Docker:
        def __init__(self, *_, **__):
            self.networks = _Networks()

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Docker)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network("atm10_default")

    assert connected == [("atm10_default", "selfid")]


async def test_detach_self_from_network_calls_disconnect(env, monkeypatch):
    disconnected: list[tuple[str, str]] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def disconnect(self, *, container):
            disconnected.append((self.name, container))

    class _Networks:
        async def get(self, name):
            return _Network(name)

    class _Docker:
        def __init__(self, *_, **__):
            self.networks = _Networks()

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Docker)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.detach_self_from_network("atm10_default")

    assert disconnected == [("atm10_default", "selfid")]
