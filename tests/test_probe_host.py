"""Resolution paths for the TCP probe host (F-3 / T-3)."""

from unittest.mock import MagicMock

from mcontrol.infra import docker_client, probe_host
from mcontrol.settings import get_settings


def _reset(monkeypatch):
    probe_host.reset()
    get_settings.cache_clear()
    monkeypatch.delenv("PROBE_HOST", raising=False)


async def test_resolve_uses_configured_setting(env, monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("PROBE_HOST", "10.0.0.1")
    get_settings.cache_clear()
    docker = MagicMock()

    result = await probe_host.resolve(docker)

    assert result == "10.0.0.1"
    assert probe_host.probe_host() == "10.0.0.1"
    docker.containers.get.assert_not_called()


async def test_resolve_uses_docker_gateway(env, monkeypatch):
    _reset(monkeypatch)
    get_settings.cache_clear()

    async def fake_gw(_docker):
        return "172.18.0.1"

    monkeypatch.setattr(docker_client, "self_network_gateway", fake_gw)

    result = await probe_host.resolve(object())

    assert result == "172.18.0.1"
    assert probe_host.probe_host() == "172.18.0.1"


async def test_resolve_falls_back_to_loopback_when_no_gateway(env, monkeypatch):
    _reset(monkeypatch)
    get_settings.cache_clear()

    async def fake_gw(_docker):
        return None

    monkeypatch.setattr(docker_client, "self_network_gateway", fake_gw)

    result = await probe_host.resolve(object())

    assert result == "127.0.0.1"
    assert probe_host.probe_host() == "127.0.0.1"


async def test_resolve_does_not_cache_inspect_failure(env, monkeypatch):
    _reset(monkeypatch)
    get_settings.cache_clear()

    async def boom(_docker):
        raise RuntimeError("daemon down")

    monkeypatch.setattr(docker_client, "self_network_gateway", boom)

    result = await probe_host.resolve(object())

    assert result == "127.0.0.1"
    assert probe_host._resolved is None


def test_probe_host_sync_uses_setting_before_resolve(env, monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("PROBE_HOST", "192.168.1.1")
    get_settings.cache_clear()

    assert probe_host.probe_host() == "192.168.1.1"


def test_probe_host_sync_defaults_to_loopback(env, monkeypatch):
    _reset(monkeypatch)
    get_settings.cache_clear()

    assert probe_host.probe_host() == "127.0.0.1"


def test_lifecycle_service_reexports_probe_host():
    from mcontrol.services.lifecycle_service import probe_host as exported

    assert exported is probe_host.probe_host
