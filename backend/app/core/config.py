"""Application settings, loaded from environment variables / backend/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "WaitLess API"
    app_version: str = "0.2.0"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:4200"])

    # Database.
    # The app connects as a NON-owner role (DB_USER) so Row-Level Security always applies (decision D30).
    # Migrations and setup scripts connect as the database owner (DB_MIGRATION_USER).
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "waitless_app"
    db_password: str = ""
    db_migration_user: str = "postgres"
    db_migration_password: str = ""
    db_name: str = "waitless"
    db_name_test: str = "waitless_test"
    db_pool_size: int = 10
    db_echo: bool = False

    # Redis / Memurai. Empty string disables Redis (single-process fallback).
    redis_url: str = "redis://127.0.0.1:6379/0"  # 127.0.0.1: avoids a ~2 s IPv6 fallback on Windows

    # Auth
    jwt_secret: str = _DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    default_country_code: str = "+91"

    # Rate limits (per client IP). Raise in development .env when running e2e tests repeatedly.
    register_limit_per_hour: int = 10

    # SaaS
    trial_plan_code: str = "professional"

    # Storage
    storage_backend: Literal["local"] = "local"
    media_root: Path = BACKEND_DIR / "uploads"
    media_url: str = "/media"
    max_upload_mb: int = 5

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    @model_validator(mode="after")
    def _production_safety(self) -> "Settings":
        if self.environment == "production" and (self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret) < 32):
            raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters in production")
        return self

    def database_url(self, *, test: bool = False, migration: bool = False, driver: str = "postgresql+asyncpg") -> URL:
        return URL.create(
            drivername=driver,
            username=self.db_migration_user if migration else self.db_user,
            password=(self.db_migration_password if migration else self.db_password) or None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name_test if test else self.db_name,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def expose_dev_codes(self) -> bool:
        """OTP codes are returned in API responses only outside production (no SMS provider yet)."""
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
