from functools import lru_cache
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
