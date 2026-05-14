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

    from mcontrol import discovery, main

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

    from mcontrol import discovery, main

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


async def test_lifespan_closes_docker_client_on_shutdown(
    env, monkeypatch, tmp_path, fake_docker_factory
):
    """The shared aiodocker client opened in lifespan startup must be
    closed during shutdown (decision #98)."""
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    from mcontrol import discovery, main

    async def _noop(_docker, _base_path):
        return 0

    monkeypatch.setattr(discovery, "run_discovery", _noop)

    app = main.create_app()
    async with app.router.lifespan_context(app):
        pass

    fake_docker_factory.close.assert_awaited()
