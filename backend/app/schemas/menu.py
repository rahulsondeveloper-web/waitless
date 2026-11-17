import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.models.menu import ALLERGENS
from app.schemas.common import ApiModel

FoodClass = Literal["veg", "non_veg", "egg"]
Allergen = Literal[ALLERGENS]  # type: ignore[valid-type]
NameStr = Annotated[str, Field(min_length=1, max_length=80)]


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

    @field_validator("allergens")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


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
