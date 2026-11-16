import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.auth import SubscriptionOut
from app.schemas.common import ApiModel, Password, PhoneNumber

RESTAURANT_TYPES = (
    "Fine Dining",
    "Casual Dining",
    "Cafe",
    "Quick Service",
    "Bar & Restaurant",
    "Bakery & Desserts",
    "Cloud Kitchen",
    "Food Court",
    "Other",
)


class RestaurantRegistration(ApiModel):
    """PRD §4 initial information."""

    restaurant_name: str = Field(min_length=2, max_length=120)
    owner_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    mobile: PhoneNumber
    password: Password
    address: str = Field(min_length=5, max_length=300)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    country: str = Field(default="India", min_length=2, max_length=80)
    cuisines: list[str] = Field(min_length=1, max_length=10)
    restaurant_type: str = Field(min_length=2, max_length=60)
    number_of_branches: int = Field(default=1, ge=1, le=500)
    preferred_slug: str | None = Field(default=None, max_length=60)

    @field_validator("cuisines")
    @classmethod
    def _clean_cuisines(cls, v: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(c.strip()[:60] for c in v if c and c.strip()))
        if not cleaned:
            raise ValueError("Select at least one cuisine.")
        return cleaned


class SlugAvailability(ApiModel):
    slug: str
    available: bool
    suggestion: str | None = None


class BranchOut(ApiModel):
    id: uuid.UUID
    name: str
    address_line: str
    city: str
    state: str
    country: str
    postal_code: str | None
    lat: Decimal | None
    lng: Decimal | None
    timezone: str
    phone: str | None
    is_primary: bool
    is_active: bool


class TenantOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    status_reason: str | None
    is_published: bool
    restaurant_type: str
    cuisines: list[str]
    declared_branch_count: int
    created_at: datetime
    approved_at: datetime | None


class RestaurantMeOut(ApiModel):
    tenant: TenantOut
    subscription: SubscriptionOut | None
    branches: list[BranchOut]


class RegistrationResponse(ApiModel):
    tenant: TenantOut
    message: str


class OwnerOut(ApiModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None


class RestaurantAdminRow(TenantOut):
    owner: OwnerOut | None
    city: str | None
    subscription: SubscriptionOut | None


StatusAction = Literal["approve", "reject", "activate", "suspend", "deactivate"]


class StatusChangeRequest(ApiModel):
    action: StatusAction
    reason: str | None = Field(default=None, max_length=500)
