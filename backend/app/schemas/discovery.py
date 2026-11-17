import uuid
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field

from app.schemas.common import ApiModel, PhoneNumber


class DiscoveryCard(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    short_description: str
    restaurant_type: str
    cuisines: list[str]
    city: str | None
    address: str | None
    lat: Decimal | None
    lng: Decimal | None
    logo_url: str | None
    cover_url: str | None
    primary_color: str | None
    open_now: bool
    today_hours: str | None
    distance_km: float | None
    wait_minutes: int | None = None  # Phase 6 (queue)


class DiscoveryPage(ApiModel):
    items: list[DiscoveryCard]
    page: int
    page_size: int
    total: int


class DiscoveryFilters(ApiModel):
    cities: list[str]
    cuisines: list[str]
    restaurant_types: list[str]


ContactTopic = Literal["general", "restaurant_signup", "customer", "partnership", "other"]


class ContactRequest(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: PhoneNumber | None = None
    topic: ContactTopic = "general"
    message: str = Field(min_length=10, max_length=4000)
    # Honeypot: real people never see or fill this field.
    website: str | None = Field(default=None, max_length=200)


class ContactResponse(ApiModel):
    received: bool
    message: str
