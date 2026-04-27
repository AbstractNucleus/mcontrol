from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient


async def test_lifespan_runs_discovery_with_settings_path(env, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    captured = {}
    fake_run = AsyncMock(return_value=0)

    async def wrapper(base_path):
        captured["base_path"] = base_path
        return await fake_run(base_path)

    from mcontrol import discovery, main

    monkeypatch.setattr(discovery, "run_discovery", wrapper)

    app = main.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Trigger lifespan startup explicitly via the test transport.
        async with app.router.lifespan_context(app):
            await ac.get("/healthz")

    assert captured["base_path"] == tmp_path


async def test_lifespan_does_not_block_startup_on_discovery_failure(env, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    async def boom(_):
        raise RuntimeError("supabase died")

    from mcontrol import discovery, main

    monkeypatch.setattr(discovery, "run_discovery", boom)

    app = main.create_app()
    # Entering and exiting the lifespan should NOT raise.
    async with app.router.lifespan_context(app):
        pass
