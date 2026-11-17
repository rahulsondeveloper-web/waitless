import uuid
from datetime import time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, EmailStr, Field, field_validator, model_validator

from app.models.profile import SOCIAL_PLATFORMS
from app.schemas.common import ApiModel, PhoneNumber

HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
SocialPlatform = Literal[SOCIAL_PLATFORMS]  # type: ignore[valid-type]
ButtonStyle = Literal["pill", "rounded", "square"]
ThemeMode = Literal["light", "dark", "auto"]


def _https(url: AnyHttpUrl | None) -> str | None:
    if url is None:
        return None
    if url.scheme != "https":
        raise ValueError("Use a secure https:// link.")
    return str(url)


# ---------- profile ----------


class ProfileUpdate(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    restaurant_type: str = Field(min_length=2, max_length=60)
    cuisines: list[str] = Field(min_length=1, max_length=10)
    short_description: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    about_us: str = Field(default="", max_length=10000)
    contact_phone: PhoneNumber | None = None
    contact_email: EmailStr | None = None
    website: AnyHttpUrl | None = None

    @field_validator("website")
    @classmethod
    def _website_https(cls, v: AnyHttpUrl | None) -> AnyHttpUrl | None:
        _https(v)
        return v

    @field_validator("cuisines")
    @classmethod
    def _clean_cuisines(cls, v: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(c.strip()[:60] for c in v if c and c.strip()))
        if not cleaned:
            raise ValueError("Select at least one cuisine.")
        return cleaned


class ProfileOut(ApiModel):
    tenant_id: uuid.UUID
    name: str
    slug: str
    status: str
    is_published: bool
    restaurant_type: str
    cuisines: list[str]
    short_description: str
    description: str
    about_us: str
    contact_phone: str | None
    contact_email: str | None
    website: str | None
    cover_url: str | None


# ---------- branding ----------


class BrandingTokens(ApiModel):
    """Owner-editable colours (PRD §5.4). Anything omitted uses the default theme."""

    primary: HexColor | None = None
    secondary: HexColor | None = None
    accent: HexColor | None = None
    background: HexColor | None = None
    surface: HexColor | None = None
    text: HexColor | None = None


class BrandingUpdate(ApiModel):
    tokens: BrandingTokens
    button_style: ButtonStyle = "pill"
    mode: ThemeMode = "light"


class BrandingOut(ApiModel):
    logo_url: str | None
    tokens: dict[str, str]
    button_style: ButtonStyle
    mode: ThemeMode
    version: int
    is_default: bool


# ---------- gallery ----------


class GalleryItemOut(ApiModel):
    id: uuid.UUID
    url: str
    width: int
    height: int
    position: int
    caption: str


class GalleryOut(ApiModel):
    items: list[GalleryItemOut]
    max_photos: int


class GalleryCaptionUpdate(ApiModel):
    caption: str = Field(default="", max_length=160)


class GalleryReorder(ApiModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5)


# ---------- branches, hours, social ----------


class BranchLocationUpdate(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    address_line: str = Field(min_length=5, max_length=300)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    country: str = Field(min_length=2, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    lat: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=9, decimal_places=6)
    lng: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=9, decimal_places=6)
    phone: PhoneNumber | None = None

    @model_validator(mode="after")
    def _both_coordinates(self) -> "BranchLocationUpdate":
        if (self.lat is None) != (self.lng is None):
            raise ValueError("Set both latitude and longitude, or neither.")
        return self


class HoursDay(ApiModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday")
    is_closed: bool = False
    opens_at: time | None = None
    closes_at: time | None = None

    @model_validator(mode="after")
    def _times(self) -> "HoursDay":
        if self.is_closed:
            self.opens_at = self.closes_at = None
        elif self.opens_at is None or self.closes_at is None:
            raise ValueError("Opening and closing time are required on open days.")
        elif self.opens_at == self.closes_at:
            raise ValueError("Opening and closing time cannot be the same.")
        return self


class HoursUpdate(ApiModel):
    days: list[HoursDay] = Field(min_length=7, max_length=7)

    @field_validator("days")
    @classmethod
    def _all_weekdays(cls, v: list[HoursDay]) -> list[HoursDay]:
        if sorted(d.weekday for d in v) != list(range(7)):
            raise ValueError("Provide each weekday (0-6) exactly once.")
        return sorted(v, key=lambda d: d.weekday)


class HoursOut(ApiModel):
    branch_id: uuid.UUID
    days: list[HoursDay]


class SocialLinkIn(ApiModel):
    platform: SocialPlatform
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def _url_https(cls, v: AnyHttpUrl) -> AnyHttpUrl:
        _https(v)
        return v


class SocialLinkOut(ApiModel):
    platform: str
    url: str


class SocialLinksUpdate(ApiModel):
    links: list[SocialLinkIn] = Field(max_length=len(SOCIAL_PLATFORMS))

    @field_validator("links")
    @classmethod
    def _unique(cls, v: list[SocialLinkIn]) -> list[SocialLinkIn]:
        if len({link.platform for link in v}) != len(v):
            raise ValueError("Each platform can be added once.")
        return v


# ---------- publishing ----------


class ChecklistItem(ApiModel):
    key: str
    label: str
    done: bool
    required: bool
    hint: str


class PublishChecklist(ApiModel):
    items: list[ChecklistItem]
    can_publish: bool
    is_published: bool


class PublishRequest(ApiModel):
    published: bool


# ---------- public storefront ----------


class PublicBranch(ApiModel):
    id: uuid.UUID
    name: str
    address_line: str
    city: str
    state: str
    country: str
    postal_code: str | None
    lat: Decimal | None
    lng: Decimal | None
    phone: str | None
    timezone: str
    is_primary: bool
    hours: list[HoursDay]
    open_now: bool
    today_hours: str | None  # "11:00–23:00", "Closed", or null when hours are not set


class StorefrontOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    restaurant_type: str
    cuisines: list[str]
    currency: str
    is_published: bool  # false only in owner preview
    short_description: str
    description: str
    about_us: str
    contact_phone: str | None
    contact_email: str | None
    website: str | None
    cover_url: str | None
    branding: BrandingOut
    branches: list[PublicBranch]
    social_links: list[SocialLinkOut]
    gallery_count: int
