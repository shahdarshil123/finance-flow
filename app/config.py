from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FinanceFlow AI"
    environment: Literal["local", "test", "production"] = "local"

    # Default matches docker-compose.yml so local development works out of the box.
    database_url: str = "postgresql+psycopg://financeflow:financeflow@localhost:5432/financeflow"
    database_echo: bool = False
    # Fail fast instead of hanging requests when the database is unreachable.
    database_connect_timeout_seconds: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
