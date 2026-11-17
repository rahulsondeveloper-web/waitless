import uuid
from datetime import time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.models.menu import ALLERGENS
from app.schemas.common import ApiModel

FoodClass = Literal["veg", "non_veg", "egg"]
Allergen = Literal[ALLERGENS]  # type: ignore[valid-type]
NameStr = Annotated[str, Field(min_length=1, max_length=80)]
Money = Annotated[Decimal, Field(ge=0, le=999999, max_digits=8, decimal_places=2)]
TaxPct = Annotated[Decimal, Field(ge=0, le=40, max_digits=4, decimal_places=2)]
Tag = Annotated[str, Field(min_length=1, max_length=30)]


def _clean_tags(v: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip().lower() for t in v if t.strip()))


# ---------- admin: structure ----------


class MealTypeIn(ApiModel):
    name: NameStr
    is_active: bool = True


class MealTypePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class CategoryIn(ApiModel):
    name: NameStr
    description: str = Field(default="", max_length=300)
    meal_type_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    is_active: bool = True


class CategoryPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    meal_type_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=8)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class SubcategoryIn(ApiModel):
    name: NameStr


class SubcategoryPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0, le=999)


# ---------- admin: items ----------


class ItemIn(ApiModel):
    category_id: uuid.UUID
    subcategory_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    base_price: Decimal = Field(ge=0, le=999999, max_digits=8, decimal_places=2)
    food_class: FoodClass = "veg"
    spice_level: int = Field(default=0, ge=0, le=3)
    allergens: list[Allergen] = Field(default_factory=list, max_length=len(ALLERGENS))
    prep_minutes: int = Field(default=15, ge=0, le=240)
    is_bestseller: bool = False
    is_todays_special: bool = False
    is_available: bool = True
    tax_pct: TaxPct = Decimal("5")
    tags: list[Tag] = Field(default_factory=list, max_length=10)

    @field_validator("allergens")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class ItemPatch(ApiModel):
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    base_price: Decimal | None = Field(default=None, ge=0, le=999999, max_digits=8, decimal_places=2)
    food_class: FoodClass | None = None
    spice_level: int | None = Field(default=None, ge=0, le=3)
    allergens: list[Allergen] | None = None
    prep_minutes: int | None = Field(default=None, ge=0, le=240)
    is_bestseller: bool | None = None
    is_todays_special: bool | None = None
    is_available: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    tax_pct: TaxPct | None = None
    tags: list[Tag] | None = Field(default=None, max_length=10)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_tags(v)


# ---------- admin: item options (Phase 7) ----------


class VariantIn(ApiModel):
    name: str = Field(min_length=1, max_length=40)
    price: Money


class AddonIn(ApiModel):
    name: str = Field(min_length=1, max_length=60)
    price: Money = Decimal("0")


class AddonGroupIn(ApiModel):
    name: str = Field(min_length=1, max_length=60)
    min_select: int = Field(default=0, ge=0, le=20)
    max_select: int = Field(default=1, ge=1, le=20)
    addons: list[AddonIn] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _range(self) -> "AddonGroupIn":
        if self.min_select > self.max_select:
            raise ValueError("Minimum choices cannot exceed the maximum.")
        if self.min_select > len(self.addons):
            raise ValueError("Minimum choices cannot exceed the number of add-ons.")
        return self


class AvailabilityIn(ApiModel):
    weekday: int = Field(ge=0, le=6)
    from_time: time
    to_time: time

    @model_validator(mode="after")
    def _order(self) -> "AvailabilityIn":
        if self.from_time >= self.to_time:
            raise ValueError("The window must end after it starts (same day).")
        return self


class ItemOptionsIn(ApiModel):
    """Replaces all variants, add-on groups and time windows of a dish in one go."""

    variants: list[VariantIn] = Field(default_factory=list, max_length=10)
    addon_groups: list[AddonGroupIn] = Field(default_factory=list, max_length=10)
    availability: list[AvailabilityIn] = Field(default_factory=list, max_length=21)

    @model_validator(mode="after")
    def _unique(self) -> "ItemOptionsIn":
        names = [v.name.strip().lower() for v in self.variants]
        if len(names) != len(set(names)):
            raise ValueError("Variant names must be unique.")
        return self


class BranchOverrideIn(ApiModel):
    is_available: bool = True
    price_override: Money | None = None


class VariantOut(ApiModel):
    id: uuid.UUID
    name: str
    price: Decimal


class AddonOut(ApiModel):
    id: uuid.UUID
    name: str
    price: Decimal


class AddonGroupOut(ApiModel):
    id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    addons: list[AddonOut]


class AvailabilityOut(ApiModel):
    weekday: int
    from_time: time
    to_time: time


class BranchOverrideOut(ApiModel):
    branch_id: uuid.UUID
    is_available: bool
    price_override: Decimal | None


class StockPatch(ApiModel):
    is_available: bool


class ItemOut(ApiModel):
    id: uuid.UUID
    category_id: uuid.UUID
    subcategory_id: uuid.UUID | None
    name: str
    description: str
    image_url: str | None
    base_price: Decimal
    food_class: FoodClass
    spice_level: int
    allergens: list[str]
    prep_minutes: int
    is_bestseller: bool
    is_todays_special: bool
    is_available: bool
    is_archived: bool
    sort_order: int
    tax_pct: Decimal = Decimal("5")
    tags: list[str] = Field(default_factory=list)
    variants: list[VariantOut] = Field(default_factory=list)
    addon_groups: list[AddonGroupOut] = Field(default_factory=list)
    availability: list[AvailabilityOut] = Field(default_factory=list)
    branch_overrides: list[BranchOverrideOut] = Field(default_factory=list)


class SubcategoryOut(ApiModel):
    id: uuid.UUID
    name: str
    sort_order: int


class CategoryOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    meal_type_ids: list[uuid.UUID]
    is_active: bool
    is_alcoholic: bool
    sort_order: int
    subcategories: list[SubcategoryOut]
    item_count: int


class MealTypeOut(ApiModel):
    id: uuid.UUID
    name: str
    is_active: bool
    sort_order: int


class AdminMenu(ApiModel):
    meal_types: list[MealTypeOut]
    categories: list[CategoryOut]
    items: list[ItemOut]
    alcohol_licensed: bool


# ---------- public ----------


class PublicItem(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    image_url: str | None
    price: Decimal
    food_class: FoodClass
    spice_level: int
    allergens: list[str]
    prep_minutes: int
    is_bestseller: bool
    is_todays_special: bool
    is_available: bool
    subcategory: str | None
    tax_pct: Decimal = Decimal("5")
    tags: list[str] = Field(default_factory=list)
    variants: list[VariantOut] = Field(default_factory=list)
    addon_groups: list[AddonGroupOut] = Field(default_factory=list)
    availability: list[AvailabilityOut] = Field(default_factory=list)  # empty = whenever open
    branch_overrides: list[BranchOverrideOut] = Field(default_factory=list)


class PublicCategory(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    meal_type_ids: list[uuid.UUID]
    items: list[PublicItem]


class PublicMealType(ApiModel):
    id: uuid.UUID
    name: str


class PublicMenu(ApiModel):
    """Only active meal types/categories that contain at least one non-archived item."""

    currency: str
    meal_types: list[PublicMealType]
    categories: list[PublicCategory]
    ordering_enabled: bool = False  # plan includes digital ordering (Phase 7)
