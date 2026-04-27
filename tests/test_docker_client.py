from unittest.mock import AsyncMock, MagicMock

import pytest

from mcontrol import docker_client


class _FakeContainer:
    def __init__(self, name: str, status: str):
        self._name = name
        self._status = status

    async def show(self) -> dict:
        return {"Name": f"/{self._name}", "State": {"Status": self._status}}


class _FakeContainers:
    def __init__(self, containers: list[_FakeContainer]):
        self._containers = containers

    async def list(self, all: bool = False) -> list[_FakeContainer]:  # noqa: A002
        assert all is True, "discovery must list ALL containers, including stopped"
        return self._containers


class _FakeDocker:
    def __init__(self, containers: list[_FakeContainer]):
        self.containers = _FakeContainers(containers)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_docker(monkeypatch):
    containers: list[_FakeContainer] = []

    def factory(*, url: str | None = None) -> _FakeDocker:
        return _FakeDocker(containers)

    monkeypatch.setattr(docker_client.aiodocker, "Docker", factory)
    return containers


async def test_container_states_by_name_returns_mapping(env, fake_docker):
    fake_docker.append(_FakeContainer("atm10", "running"))
    fake_docker.append(_FakeContainer("monifactory", "exited"))

    states = await docker_client.container_states_by_name()

    assert states == {"atm10": "running", "monifactory": "exited"}


async def test_container_states_strips_leading_slash(env, fake_docker):
    fake_docker.append(_FakeContainer("kobra_kollektivet", "created"))

    states = await docker_client.container_states_by_name()

    assert states == {"kobra_kollektivet": "created"}


async def test_container_states_returns_empty_when_docker_unreachable(env, monkeypatch):
    class _Boom:
        def __init__(self, *_, **__):
            raise RuntimeError("docker daemon is sulking")

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Boom)

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
