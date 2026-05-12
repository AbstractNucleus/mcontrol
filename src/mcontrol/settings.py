from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    server_base_path: str
    docker_host: str = "unix:///var/run/docker.sock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
