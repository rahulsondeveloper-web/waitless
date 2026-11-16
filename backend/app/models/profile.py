"""Restaurant profile, branding, gallery, opening hours, social links, media files (PRD §5)."""

import uuid
from datetime import time
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin

MEDIA_KINDS = ("logo", "cover", "gallery")
SOCIAL_PLATFORMS = ("instagram", "facebook", "x", "youtube", "google", "zomato", "swiggy", "tripadvisor", "other")
GALLERY_MAX_POSITION = 5  # DB hard cap; the service enforces the configurable limit (PRD §5.3)


class MediaFile(UUIDPkMixin, CreatedAtMixin, Base):
    """An image we produced (validated, re-encoded WebP, metadata stripped). Never the raw upload."""

    __tablename__ = "media_files"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    mime: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_media_files_tenant_id_id"),
        CheckConstraint(f"kind IN {MEDIA_KINDS}", name="kind"),
    )


class RestaurantProfile(TimestampMixin, Base):
    __tablename__ = "restaurant_profiles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    short_description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    about_us: Mapped[str] = mapped_column(Text, default="", server_default="")
    contact_phone: Mapped[str | None] = mapped_column(String(16))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(300))
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "cover_media_id"],
            ["media_files.tenant_id", "media_files.id"],
            name="fk_restaurant_profiles_cover_media",
            ondelete="SET NULL (cover_media_id)",
        ),
    )


class RestaurantBranding(TimestampMixin, Base):
    __tablename__ = "restaurant_branding"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    logo_media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Colour tokens (hex). Empty = default theme (decision D1).
    tokens: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    button_style: Mapped[str] = mapped_column(String(10), default="pill", server_default="pill")
    mode: Mapped[str] = mapped_column(String(10), default="light", server_default="light")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "logo_media_id"],
            ["media_files.tenant_id", "media_files.id"],
            name="fk_restaurant_branding_logo_media",
            ondelete="SET NULL (logo_media_id)",
        ),
        CheckConstraint("button_style IN ('pill', 'rounded', 'square')", name="button_style"),
        CheckConstraint("mode IN ('light', 'dark', 'auto')", name="mode"),
    )


class GalleryImage(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "restaurant_gallery"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    media_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    position: Mapped[int] = mapped_column(SmallInteger)
    caption: Mapped[str] = mapped_column(String(160), default="", server_default="")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "media_id"], ["media_files.tenant_id", "media_files.id"], ondelete="CASCADE"
        ),
        # At most 5 photos: positions 1..5, each used once. Deferred so reordering can swap positions.
        UniqueConstraint(
            "tenant_id", "position", name="uq_restaurant_gallery_tenant_position", deferrable=True, initially="DEFERRED"
        ),
        CheckConstraint(f"position BETWEEN 1 AND {GALLERY_MAX_POSITION}", name="position_range"),
    )


class BusinessHours(UUIDPkMixin, Base):
    """One opening window per branch per weekday (0 = Monday). closes_at < opens_at means past midnight."""

    __tablename__ = "restaurant_business_hours"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        UniqueConstraint("branch_id", "weekday", name="uq_restaurant_business_hours_branch_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
        CheckConstraint(
            "is_closed OR (opens_at IS NOT NULL AND closes_at IS NOT NULL AND opens_at <> closes_at)",
            name="times_when_open",
        ),
    )


class SocialLink(UUIDPkMixin, Base):
    __tablename__ = "restaurant_social_links"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", name="uq_restaurant_social_links_tenant_platform"),
        CheckConstraint(f"platform IN {SOCIAL_PLATFORMS}", name="platform"),
        CheckConstraint("url ~ '^https://'", name="https_url"),
    )
