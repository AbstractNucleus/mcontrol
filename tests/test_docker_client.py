import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiodocker
import pytest

from mcontrol.infra import docker_client


@pytest.fixture(autouse=True)
def _reset_network_refcounts(monkeypatch):
    """The attach/detach refcounts are module state; keep tests isolated."""
    monkeypatch.setattr(docker_client, "_DETACH_COOLDOWN_S", 0)
    docker_client._network_refcounts.clear()
    docker_client._network_attach_locks.clear()
    for task in list(docker_client._inflight_connects.values()):
        task.cancel()
    docker_client._inflight_connects.clear()
    for task in list(docker_client._pending_detaches.values()):
        task.cancel()
    docker_client._pending_detaches.clear()
    yield
    for task in list(docker_client._inflight_connects.values()):
        task.cancel()
    docker_client._inflight_connects.clear()
    for task in list(docker_client._pending_detaches.values()):
        task.cancel()
    docker_client._pending_detaches.clear()
    docker_client._network_refcounts.clear()
    docker_client._network_attach_locks.clear()


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


async def test_container_state_reads_authoritative_inspect_status(env):
    container = MagicMock()
    container.show = AsyncMock(return_value={"State": {"Status": "exited"}})
    docker = MagicMock()
    docker.containers.get = AsyncMock(return_value=container)

    assert await docker_client.container_state(docker, "atm10") == "exited"
    docker.containers.get.assert_awaited_once_with("atm10")


async def test_container_state_returns_none_only_for_confirmed_404(env):
    docker = MagicMock()
    docker.containers.get = AsyncMock(
        side_effect=aiodocker.DockerError(404, {"message": "not found"})
    )

    assert await docker_client.container_state(docker, "atm10") is None


async def test_container_state_propagates_daemon_failure(env):
    docker = MagicMock()
    docker.containers.get = AsyncMock(
        side_effect=aiodocker.DockerError(500, {"message": "daemon failed"})
    )

    with pytest.raises(aiodocker.DockerError):
        await docker_client.container_state(docker, "atm10")


# --- Slice 4: lifecycle / logs / network helpers ----------------------------


class _FakeContainer:
    def __init__(self, name: str = "atm10", networks: dict | None = None):
        self.name = name
        self._started = False
        self._stopped = False
        self._restarted = False
        self._deleted = False
        self._stop_kwargs: dict = {}
        self._delete_kwargs: dict = {}
        nets = networks if networks is not None else {"atm10_default": {}}
        self._show_data = {
            "Name": f"/{name}",
            "NetworkSettings": {"Networks": nets},
        }

    async def start(self) -> None:
        self._started = True

    async def stop(self, **kwargs) -> None:
        self._stopped = True
        self._stop_kwargs = kwargs

    async def delete(self, **kwargs) -> None:
        self._deleted = True
        self._delete_kwargs = kwargs

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
    assert fake._stop_kwargs.get("t") == 90


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
        async def stop(self, **_kwargs):
            await asyncio.sleep(9999)

    docker = _docker_with_container(_HangingContainer())
    monkeypatch.setattr(docker_client, "_STOP_WAIT_S", 0.01)

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
    connected: list[tuple[str, dict[str, str]]] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def connect(self, config):
            connected.append((self.name, config))

    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(side_effect=lambda name: _Network(name))
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")

    assert connected == [("atm10_default", {"Container": "selfid"})]


async def test_attach_already_connected_is_refcounted(env, monkeypatch):
    network = MagicMock()
    network.connect = AsyncMock(
        side_effect=aiodocker.DockerError(
            403,
            "endpoint with name mcontrol already exists in network atm10_default",
        )
    )
    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(return_value=network)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")

    assert docker_client._network_refcounts["atm10_default"] == 1


async def test_attach_unexpected_failure_propagates_without_refcount(
    env, monkeypatch
):
    network = MagicMock()
    network.connect = AsyncMock(
        side_effect=aiodocker.DockerError(500, "unexpected network failure")
    )
    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(return_value=network)
    monkeypatch.setenv("HOSTNAME", "selfid")

    with pytest.raises(aiodocker.DockerError, match="unexpected network failure"):
        await docker_client.attach_self_to_network(docker, "atm10_default")

    network.connect.assert_awaited_once_with({"Container": "selfid"})
    assert "atm10_default" not in docker_client._network_refcounts


async def test_attach_skips_connect_when_already_on_network(env, monkeypatch):
    network = MagicMock()
    network.connect = AsyncMock()

    class _Container:
        async def show(self):
            return {"NetworkSettings": {"Networks": {"atm10_default": {}}}}

    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(return_value=network)
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(return_value=_Container())
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")

    network.connect.assert_not_called()
    docker.networks.get.assert_not_called()
    assert docker_client._network_refcounts["atm10_default"] == 1


async def test_attach_timeout_succeeds_if_inspect_shows_connected(
    env, monkeypatch
):
    """Hung NetworkConnect: if cancelling the HTTP call left us joined,
    treat it as success so the console can emit ready."""
    shows = {"n": 0}

    class _Container:
        async def show(self):
            shows["n"] += 1
            names = {} if shows["n"] == 1 else {"atm10_default": {}}
            return {"NetworkSettings": {"Networks": names}}

    network = MagicMock()
    network.connect = AsyncMock(side_effect=TimeoutError())
    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(return_value=network)
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(return_value=_Container())
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")

    network.connect.assert_awaited_once_with({"Container": "selfid"})
    assert docker_client._network_refcounts["atm10_default"] == 1


async def test_attach_timeout_raises_when_still_disconnected(env, monkeypatch):
    class _Container:
        async def show(self):
            return {"NetworkSettings": {"Networks": {}}}

    network = MagicMock()
    network.connect = AsyncMock(side_effect=TimeoutError())
    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(return_value=network)
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(return_value=_Container())
    monkeypatch.setenv("HOSTNAME", "selfid")

    with pytest.raises(TimeoutError):
        await docker_client.attach_self_to_network(docker, "atm10_default")

    assert "atm10_default" not in docker_client._network_refcounts


async def test_attach_timeout_returns_even_if_connect_ignores_cancel(
    env, monkeypatch
):
    """wait_for() on an un-cancellable NetworkConnect used to block past 8s
    (aiohttp sock_read). Shield so the 8s bound actually returns."""
    monkeypatch.setattr(docker_client, "_ATTACH_TIMEOUT_S", 0.05)
    stop = asyncio.Event()
    started = {"n": 0}

    class _Network:
        async def connect(self, config):  # noqa: ARG002
            started["n"] += 1
            while not stop.is_set():
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    continue

    class _Container:
        async def show(self):
            return {"NetworkSettings": {"Networks": {}}}

    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(return_value=_Network())
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(return_value=_Container())
    monkeypatch.setenv("HOSTNAME", "selfid")

    try:
        async with asyncio.timeout(1):
            with pytest.raises(TimeoutError):
                await docker_client.attach_self_to_network(docker, "atm10_default")
    finally:
        stop.set()
        inflight = docker_client._inflight_connects.get("atm10_default")
        if inflight is not None:
            await asyncio.wait_for(inflight, timeout=1)

    assert started["n"] == 1
    assert "atm10_default" not in docker_client._network_refcounts


async def test_detach_cooldown_cancelled_by_reattach(env, monkeypatch):
    """Last subscriber leaving must not NetworkDisconnect immediately:
    a reconnecting EventSource would flap our netns and kill the new SSE."""
    monkeypatch.setattr(docker_client, "_DETACH_COOLDOWN_S", 0.15)
    connects: list = []
    disconnects: list = []
    docker = _refcount_docker(connects, disconnects)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")
    await docker_client.detach_self_from_network(docker, "atm10_default")
    assert disconnects == []

    await docker_client.attach_self_to_network(docker, "atm10_default")
    await asyncio.sleep(0.25)
    assert disconnects == []

    await docker_client.detach_self_from_network(docker, "atm10_default")
    await asyncio.sleep(0.25)
    assert disconnects == [("atm10_default", {"Container": "selfid"})]


async def test_detach_self_from_network_calls_disconnect(env, monkeypatch):
    disconnected: list[tuple[str, dict[str, str]]] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def connect(self, config):
            pass

        async def disconnect(self, config):
            disconnected.append((self.name, config))

    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(side_effect=lambda name: _Network(name))
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")
    await docker_client.detach_self_from_network(docker, "atm10_default")

    assert disconnected == [("atm10_default", {"Container": "selfid"})]


class _CountingNetwork:
    def __init__(self, name, connects, disconnects):
        self.name = name
        self._connects = connects
        self._disconnects = disconnects

    async def connect(self, config):
        self._connects.append((self.name, config))

    async def disconnect(self, config):
        self._disconnects.append((self.name, config))


def _refcount_docker(connects: list, disconnects: list) -> MagicMock:
    docker = MagicMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(
        side_effect=lambda name: _CountingNetwork(name, connects, disconnects)
    )
    return docker


async def test_attach_detach_are_refcounted(env, monkeypatch):
    """Two holders (console SSE + one-shot RCON) share one membership:
    the second attach doesn't re-connect and the first detach doesn't
    disconnect; only the final detach does."""
    connects: list = []
    disconnects: list = []
    docker = _refcount_docker(connects, disconnects)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")
    await docker_client.attach_self_to_network(docker, "atm10_default")
    assert connects == [("atm10_default", {"Container": "selfid"})]

    await docker_client.detach_self_from_network(docker, "atm10_default")
    assert disconnects == []

    await docker_client.detach_self_from_network(docker, "atm10_default")
    assert disconnects == [("atm10_default", {"Container": "selfid"})]


async def test_detach_without_attach_is_a_noop(env, monkeypatch):
    disconnects: list = []
    docker = _refcount_docker([], disconnects)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.detach_self_from_network(docker, "atm10_default")

    assert disconnects == []


async def test_refcounts_are_per_network(env, monkeypatch):
    connects: list = []
    disconnects: list = []
    docker = _refcount_docker(connects, disconnects)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network(docker, "atm10_default")
    await docker_client.attach_self_to_network(docker, "moni_default")
    await docker_client.detach_self_from_network(docker, "atm10_default")

    assert connects == [
        ("atm10_default", {"Container": "selfid"}),
        ("moni_default", {"Container": "selfid"}),
    ]
    assert disconnects == [("atm10_default", {"Container": "selfid"})]


async def test_remove_container_calls_delete(env):
    fake = _FakeContainer()
    docker = _docker_with_container(fake)

    await docker_client.remove_container(docker, "atm10")

    assert fake._deleted is True
    assert fake._delete_kwargs.get("v") is False


async def test_remove_container_ignores_404(env):
    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(
        side_effect=aiodocker.DockerError(404, {"message": "No such container"})
    )

    await docker_client.remove_container(docker, "atm10")


async def test_self_network_gateway_returns_first_gateway(env, monkeypatch):
    class _Container:
        async def show(self):
            return {
                "NetworkSettings": {
                    "Networks": {
                        "mcontrol_default": {"Gateway": "172.18.0.1"},
                        "other": {"Gateway": "172.19.0.1"},
                    }
                }
            }

    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(return_value=_Container())
    monkeypatch.setenv("HOSTNAME", "selfid")

    assert await docker_client.self_network_gateway(docker) == "172.18.0.1"


async def test_self_network_gateway_none_when_not_in_docker(env, monkeypatch):
    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(
        side_effect=aiodocker.DockerError(404, {"message": "nope"})
    )
    monkeypatch.setenv("HOSTNAME", "not-a-container")

    assert await docker_client.self_network_gateway(docker) is None


async def test_prune_disconnects_server_networks_keeps_home(env, monkeypatch):
    disconnected: list[str] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def disconnect(self, config):  # noqa: ARG002
            disconnected.append(self.name)

    class _Container:
        async def show(self):
            return {
                "HostConfig": {"NetworkMode": "mcontrol_default"},
                "Config": {"Labels": {"com.docker.compose.project": "mcontrol"}},
                "NetworkSettings": {
                    "Networks": {
                        "mcontrol_default": {},
                        "loading_default": {},
                        "atm10-030826_default": {},
                    }
                },
            }

    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(return_value=_Container())
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock(side_effect=lambda name: _Network(name))
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.prune_stale_self_networks(docker)

    assert set(disconnected) == {"loading_default", "atm10-030826_default"}


async def test_prune_is_noop_when_not_in_docker(env, monkeypatch):
    docker = MagicMock()
    docker.containers = MagicMock()
    docker.containers.get = AsyncMock(
        side_effect=aiodocker.DockerError(404, {"message": "nope"})
    )
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock()
    monkeypatch.setenv("HOSTNAME", "not-a-container")

    await docker_client.prune_stale_self_networks(docker)

    docker.networks.get.assert_not_called()


async def test_disconnect_refcount_networks_clears(env, monkeypatch):
    disconnects: list = []
    docker = _refcount_docker([], disconnects)
    monkeypatch.setenv("HOSTNAME", "selfid")
    docker_client._network_refcounts["atm10_default"] = 1

    await docker_client.disconnect_refcount_networks(docker)

    assert disconnects == [("atm10_default", {"Container": "selfid"})]
    assert docker_client._network_refcounts == {}
