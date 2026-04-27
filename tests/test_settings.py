import pytest

from mcontrol.settings import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", "/home/abstract/servers/minecraft")

    settings = Settings()

    assert settings.supabase_url == "https://api.noelkleen.com"
    assert settings.supabase_service_role_key == "test-key"
    assert settings.server_base_path == "/home/abstract/servers/minecraft"


def test_settings_missing_required_field_raises(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SERVER_BASE_PATH", raising=False)

    with pytest.raises(Exception):
        Settings(_env_file=None)
