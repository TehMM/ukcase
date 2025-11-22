import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="UKCASE_",
    )

    app_env: str = "dev"
    # The following environment variables are required for runtime configuration.
    database_url: str
    redis_url: str
    app_base_url: str | None = None

    # Admin credentials must be supplied via environment variables.
    admin_username: str
    admin_password: str

    default_rate_limit_seconds: float = 1.5
    request_timeout_seconds: int = 20
    max_http_retries: int = 4

    http_user_agent: str = "ukcase-scraper/0.1 (+contact: CHANGE_ME)"
    xml_storage_root: Path = Path("./data/xml")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    settings = Settings()

    # When running with the lightweight test stubs (no pydantic_settings), populate
    # required fields from environment variables to mirror BaseSettings behaviour.
    settings.database_url = getattr(
        settings,
        "database_url",
        os.environ.get("UKCASE_DATABASE_URL", "sqlite+pysqlite:///"),
    )
    settings.redis_url = getattr(
        settings, "redis_url", os.environ.get("UKCASE_REDIS_URL", "redis://localhost:6379/0")
    )
    settings.admin_username = getattr(
        settings, "admin_username", os.environ.get("UKCASE_ADMIN_USERNAME", "admin")
    )
    settings.admin_password = getattr(
        settings, "admin_password", os.environ.get("UKCASE_ADMIN_PASSWORD", "password")
    )
    return settings
