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
    contact_limit_per_hour: int = 5
    login_ip_limit_per_15min: int = 30  # per-account limit (5) is fixed

    # SaaS
    trial_plan_code: str = "professional"

    # Booking payments (decision D17). "mock" works offline; "razorpay" needs the three keys below.
    payment_provider: Literal["mock", "razorpay"] = "mock"
    mock_webhook_secret: str = "dev-mock-webhook-secret"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    payment_hold_minutes: int = 15  # unpaid paid-bookings release their table after this

    # Restaurant storefront (PRD §5.3: change only together with the DB check constraint)
    gallery_max_photos: int = 5
    storefront_cache_seconds: int = 60

    # Storage (decision D26). "s3" works with AWS S3 and S3-compatible stores (MinIO, Cloudflare R2).
    storage_backend: Literal["local", "s3"] = "local"
    media_root: Path = BACKEND_DIR / "uploads"
    media_url: str = "/media"
    max_upload_mb: int = 5
    s3_bucket: str = ""
    s3_region: str = "ap-south-1"
    s3_endpoint_url: str = ""  # empty = AWS; set for MinIO / R2
    s3_public_base_url: str = ""  # CDN / CloudFront URL in front of the bucket; empty = bucket URL
    s3_prefix: str = "media"
    # Credentials come from the standard AWS chain (env AWS_ACCESS_KEY_ID/SECRET or an IAM role).

    # Maps & geocoding (decision D25). Nominatim by default; Google when a key is set.
    maps_provider: Literal["nominatim", "google"] = "nominatim"
    google_maps_api_key: str = ""
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    geocode_user_agent: str = "WaitLess/1.0 (restaurant platform)"

    # Messaging (PRD §25). "console" logs only (development).
    sms_provider: Literal["console", "msg91", "twilio"] = "console"
    whatsapp_provider: Literal["console", "twilio", "meta"] = "console"
    email_provider: Literal["console", "smtp"] = "console"
    msg91_auth_key: str = ""
    msg91_sender_id: str = "WAITLS"
    msg91_otp_template_id: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_sms_from: str = ""
    twilio_whatsapp_from: str = ""  # e.g. whatsapp:+14155238886
    meta_whatsapp_token: str = ""
    meta_whatsapp_phone_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "WaitLess <no-reply@waitless.app>"
    smtp_starttls: bool = True

    # Operations
    public_base_url: str = "http://localhost:4200"  # used in links inside messages and invoices
    metrics_token: str = ""  # /api/v1/metrics needs "Authorization: Bearer <token>" (empty = disabled)
    api_docs: bool | None = None  # None = on outside production

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    @model_validator(mode="after")
    def _production_safety(self) -> "Settings":
        """Refuse to start in production with development defaults (security review, Phase 12)."""
        if self.environment != "production":
            return self
        problems = []
        if self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a random value of at least 32 characters")
        if not self.db_password:
            problems.append("DB_PASSWORD is required")
        if self.payment_provider == "mock":
            problems.append("PAYMENT_PROVIDER=mock is not allowed (use razorpay)")
        if self.payment_provider == "razorpay" and not (
            self.razorpay_key_id and self.razorpay_key_secret and self.razorpay_webhook_secret
        ):
            problems.append("RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET are required")
        if any(o.startswith("http://localhost") or o == "*" for o in self.cors_origins):
            problems.append("CORS_ORIGINS must list the real https origins")
        if self.debug:
            problems.append("DEBUG must be off")
        if self.storage_backend == "s3" and not self.s3_bucket:
            problems.append("S3_BUCKET is required with STORAGE_BACKEND=s3")
        if self.maps_provider == "google" and not self.google_maps_api_key:
            problems.append("GOOGLE_MAPS_API_KEY is required with MAPS_PROVIDER=google")
        if self.sms_provider == "console":
            problems.append("SMS_PROVIDER must be a real provider (msg91 or twilio): guests sign in with SMS codes")
        if problems:
            raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs if self.api_docs is not None else not self.is_production

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
