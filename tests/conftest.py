from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from mcontrol.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()


@pytest.fixture
def env(monkeypatch):
    """Default test environment — required Settings fields populated."""
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", "/tmp/mcontrol-test-servers")


@pytest.fixture
async def client(env) -> AsyncIterator[AsyncClient]:
    from mcontrol.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
