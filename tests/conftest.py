from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from mcontrol.settings import get_settings


@pytest.fixture
def server_dir(tmp_path: Path) -> Path:
    d = tmp_path / "srv"
    d.mkdir()
    return d


@pytest.fixture
def fake_server(monkeypatch, server_dir: Path):
    rows: dict[str, dict] = {
        "atm10": {"name": "atm10", "dir": str(server_dir)}
    }
    from mcontrol.infra import db
    from mcontrol.services import file_search
    monkeypatch.setattr(db, "get_server", rows.get)
    # The search index is a module-level singleton keyed by server name;
    # clear it between tests so cached state from a previous tmp_path
    # doesn't bleed into this one.
    file_search._search_index.clear()
    return rows


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()


@pytest.fixture
def env(monkeypatch):
    """Default test environment with required Settings fields populated."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", "/tmp/mcontrol-test-servers")


def make_fake_docker() -> MagicMock:
    """A pytest-friendly stand-in for an ``aiodocker.Docker`` instance.

    Tests that go through the FastAPI client (``client`` fixture) get
    one of these wired into ``app.state.docker`` so the lifespan never
    touches a real socket. Individual tests can attach more specific
    behaviour (e.g. ``docker.containers.get = AsyncMock(return_value=...)``)
    by reaching into ``client.app.state.docker``.
    """
    docker = MagicMock(name="aiodocker.Docker")
    docker.close = AsyncMock()
    docker.version = AsyncMock(return_value={"Version": "test"})
    docker.containers = MagicMock()
    docker.containers.list = AsyncMock(return_value=[])
    docker.containers.get = AsyncMock()
    docker.networks = MagicMock()
    docker.networks.get = AsyncMock()
    return docker


@pytest.fixture
def fake_docker_factory(monkeypatch):
    """Patch ``mcontrol.main.aiodocker.Docker`` so lifespan startup uses
    a fake. The same fake instance is returned to the test so it can
    attach more specific behaviour."""
    from mcontrol import main as main_mod

    fake = make_fake_docker()
    monkeypatch.setattr(main_mod.aiodocker, "Docker", lambda *_a, **_kw: fake)
    return fake


@pytest.fixture
async def client(env, fake_docker_factory) -> AsyncIterator[AsyncClient]:
    from mcontrol.main import create_app

    app = create_app()
    # ASGITransport does not run the lifespan, so app.state.docker is
    # never populated by the real startup hook. Inject the fake directly
    # so routes that Depends(get_docker) resolve cleanly.
    app.state.docker = fake_docker_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
