"""Digital menu (PRD §7). Phase 4 = structure + items; Phase 7 adds variants, add-ons, availability
windows, taxes and branch overrides on top of these tables."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin

FOOD_CLASSES = ("veg", "non_veg", "egg")
ALLERGENS = ("gluten", "dairy", "nuts", "peanuts", "soy", "egg", "fish", "shellfish", "sesame", "mustard", "celery")


class MealType(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "menu_meal_types"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_menu_meal_types_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_menu_meal_types_tenant_name"),
    )


class MenuCategory(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "menu_categories"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_alcoholic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_menu_categories_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_menu_categories_tenant_name"),
    )


class CategoryMealType(Base):
    """A category appears on one or more meal-type menus."""

    __tablename__ = "menu_category_meal_types"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    meal_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["menu_categories.tenant_id", "menu_categories.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "meal_type_id"], ["menu_meal_types.tenant_id", "menu_meal_types.id"], ondelete="CASCADE"
        ),
    )


class MenuSubcategory(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "menu_subcategories"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["menu_categories.tenant_id", "menu_categories.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_menu_subcategories_tenant_id_id"),
        UniqueConstraint("category_id", "name", name="uq_menu_subcategories_category_name"),
    )


class MenuItem(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "menu_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    food_class: Mapped[str] = mapped_column(String(10), default="veg", server_default="veg")
    spice_level: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    allergens: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list, server_default="{}")
    prep_minutes: Mapped[int] = mapped_column(SmallInteger, default=15, server_default="15")
    is_bestseller: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_todays_special: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # "sold out" toggle
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "category_id"], ["menu_categories.tenant_id", "menu_categories.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "subcategory_id"],
            ["menu_subcategories.tenant_id", "menu_subcategories.id"],
            ondelete="SET NULL (subcategory_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "image_media_id"],
            ["media_files.tenant_id", "media_files.id"],
            ondelete="SET NULL (image_media_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_menu_items_tenant_id_id"),
        CheckConstraint("base_price >= 0", name="price_non_negative"),
        CheckConstraint(f"food_class IN {FOOD_CLASSES}", name="food_class"),
        CheckConstraint("spice_level BETWEEN 0 AND 3", name="spice_level"),
        CheckConstraint("prep_minutes BETWEEN 0 AND 240", name="prep_minutes"),
        Index("ix_menu_items_category", "tenant_id", "category_id"),
    )
