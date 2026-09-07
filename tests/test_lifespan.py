import logging
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient


async def test_lifespan_runs_discovery_with_settings_path(
    env, monkeypatch, tmp_path, fake_docker_factory
):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    captured = {}
    fake_run = AsyncMock(return_value=0)

    async def wrapper(docker, base_path):
        captured["docker"] = docker
        captured["base_path"] = base_path
        return await fake_run(docker, base_path)

    from mcontrol import main
    from mcontrol.domain import discovery

    monkeypatch.setattr(discovery, "run_discovery", wrapper)

    app = main.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Trigger lifespan startup explicitly via the test transport.
        async with app.router.lifespan_context(app):
            await ac.get("/healthz")

    assert captured["base_path"] == tmp_path
    # The shared client built in lifespan is what discovery received.
    assert captured["docker"] is fake_docker_factory


async def test_lifespan_does_not_block_startup_on_discovery_failure(
    env, monkeypatch, tmp_path, caplog, fake_docker_factory
):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    async def boom(_docker, _base_path):
        raise RuntimeError("supabase died")

    from mcontrol import main
    from mcontrol.domain import discovery

    monkeypatch.setattr(discovery, "run_discovery", boom)

    app = main.create_app()
    # Entering and exiting the lifespan should NOT raise.
    with caplog.at_level(logging.ERROR, logger="mcontrol"):
        async with app.router.lifespan_context(app):
            pass

    assert any(
        "discovery failed" in record.message
        for record in caplog.records
        if record.name == "mcontrol"
    )


async def test_lifespan_constructs_docker_client_with_timeout(
    env, monkeypatch, tmp_path
):
    """A wedged daemon must not hang one-shot calls forever; the shared
    client is built with an explicit aiohttp.ClientTimeout."""
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    from mcontrol import main
    from mcontrol.domain import discovery
    from tests.conftest import make_fake_docker

    captured: dict = {}
    fake = make_fake_docker()

    def factory(*_args, **kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr(main.aiodocker, "Docker", factory)

    async def _noop(_docker, _base_path):
        return 0

    monkeypatch.setattr(discovery, "run_discovery", _noop)

    app = main.create_app()
    async with app.router.lifespan_context(app):
        pass

    timeout = captured["timeout"]
    assert (timeout.connect, timeout.sock_read, timeout.total) == (5, 30, 60)


async def test_lifespan_closes_docker_client_on_shutdown(
    env, monkeypatch, tmp_path, fake_docker_factory
):
    """The shared aiodocker client opened in lifespan startup must be
    closed during shutdown (decision #98)."""
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    from mcontrol import main
    from mcontrol.domain import discovery

    async def _noop(_docker, _base_path):
        return 0

    monkeypatch.setattr(discovery, "run_discovery", _noop)

    app = main.create_app()
    async with app.router.lifespan_context(app):
        pass

    fake_docker_factory.close.assert_awaited()


async def test_lifespan_prunes_stale_networks_and_resolves_probe_host(
    env, monkeypatch, tmp_path, fake_docker_factory
):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    from mcontrol import main
    from mcontrol.domain import discovery
    from mcontrol.infra import docker_client, probe_host

    pruned: list = []
    resolved: list = []

    async def fake_prune(docker):
        pruned.append(docker)

    async def fake_resolve(docker):
        resolved.append(docker)
        return "127.0.0.1"

    async def _noop(_docker, _base_path):
        return 0

    monkeypatch.setattr(docker_client, "prune_stale_self_networks", fake_prune)
    monkeypatch.setattr(probe_host, "resolve", fake_resolve)
    monkeypatch.setattr(discovery, "run_discovery", _noop)

    app = main.create_app()
    async with app.router.lifespan_context(app):
        pass

    assert pruned == [fake_docker_factory]
    assert resolved == [fake_docker_factory]


async def test_lifespan_disconnects_refcount_networks_on_shutdown(
    env, monkeypatch, tmp_path, fake_docker_factory
):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    from mcontrol import main
    from mcontrol.domain import discovery
    from mcontrol.infra import docker_client

    seen: list = []

    async def fake_disc(docker):
        seen.append(docker)

    async def _noop(_docker, _base_path):
        return 0

    monkeypatch.setattr(docker_client, "disconnect_refcount_networks", fake_disc)
    monkeypatch.setattr(discovery, "run_discovery", _noop)

    app = main.create_app()
    async with app.router.lifespan_context(app):
        pass

    assert seen == [fake_docker_factory]


def test_healthz_access_filter_drops_healthz_lines():
    import logging

    from mcontrol.main import _HealthzAccessFilter

    filt = _HealthzAccessFilter()
    rec = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1", "GET", "/healthz", "1.1", 200),
        exc_info=None,
    )
    assert filt.filter(rec) is False

    rec2 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1", "GET", "/", "1.1", 200),
        exc_info=None,
    )
    assert filt.filter(rec2) is True
