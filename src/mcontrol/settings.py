from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    server_base_path: str
    docker_host: str = "unix:///var/run/docker.sock"
    # Host to TCP-probe for a server's published port. Unset = auto-detect
    # (own Docker network gateway, else 127.0.0.1). See infra.probe_host.
    probe_host: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
