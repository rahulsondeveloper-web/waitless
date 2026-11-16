"""People and sessions: users (staff, owners, customers, super admins), refresh tokens, OTP challenges."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin


class User(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    phone: Mapped[str | None] = mapped_column(String(16), unique=True)  # E.164
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)  # null for OTP-only customers
    full_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="has_contact"),)


class RefreshToken(UUIDPkMixin, CreatedAtMixin, Base):
    """Rotated on every use. Reusing a rotated token revokes the whole family (theft detection)."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # active tenant carried across refresh
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (Index("ix_refresh_tokens_user_id", "user_id"),)


class OtpChallenge(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "otp_challenges"

    phone: Mapped[str] = mapped_column(String(16), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(30), default="login")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
