"""Application settings, loaded from environment variables / backend/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "WaitLess API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:4200"])

    # Database (separate parts so passwords with special characters need no URL-encoding)
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "waitless"
    db_name_test: str = "waitless_test"
    db_pool_size: int = 10
    db_echo: bool = False

    # Redis / Memurai. Empty string disables Redis (single-process fallback).
    redis_url: str = "redis://127.0.0.1:6379/0"  # 127.0.0.1: avoids a ~2 s IPv6 fallback on Windows

    # Storage
    storage_backend: Literal["local"] = "local"
    media_root: Path = BACKEND_DIR / "uploads"
    media_url: str = "/media"
    max_upload_mb: int = 5

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    def database_url(self, *, test: bool = False, driver: str = "postgresql+asyncpg") -> URL:
        return URL.create(
            drivername=driver,
            username=self.db_user,
            password=self.db_password or None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name_test if test else self.db_name,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
