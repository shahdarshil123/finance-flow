from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    # External ERP (the mock ERP service by default, see mock_erp/). 127.0.0.1,
    # not localhost: on Windows, localhost tries IPv6 first, doubling the time
    # to detect a stopped ERP.
    erp_base_url: str = "http://127.0.0.1:8001"
    erp_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    erp_read_timeout_seconds: float = Field(default=3.0, gt=0)
    # Total attempts per read request, including the first; bounds retry loops.
    erp_max_attempts: int = Field(default=3, ge=1, le=10)
    erp_backoff_base_seconds: float = Field(default=0.2, ge=0)
    # Caps each backoff sleep; a longer Retry-After ends retrying instead.
    erp_backoff_max_seconds: float = Field(default=2.0, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
