from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    database_url: str = 'postgresql+psycopg://ppe:local_dev_password_change_me@localhost:5432/ppe'
    app_env: str = 'development'
    enable_api_docs: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    model_artifact_namespace: str = ''
    media_gateway_origin: str = ''
    media_gateway_token_file: str = ''


@lru_cache

def get_settings() -> Settings:
    return Settings()
