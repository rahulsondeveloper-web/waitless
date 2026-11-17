import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import ApiModel, PhoneNumber

Scope = Literal["all", "own_branches"]


# ---------- branches ----------


class BranchCreate(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    address_line: str = Field(min_length=5, max_length=300)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    country: str = Field(default="India", min_length=2, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    phone: PhoneNumber | None = None
    timezone: str = Field(default="Asia/Kolkata", max_length=60)
    lat: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=9, decimal_places=6)
    lng: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=9, decimal_places=6)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone.") from exc
        return v


class BranchStatus(ApiModel):
    is_active: bool


# ---------- staff ----------


class StaffInvite(ApiModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: PhoneNumber
    email: EmailStr | None = None
    role_id: uuid.UUID
    all_branches: bool = False
    branch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class StaffUpdate(ApiModel):
    role_id: uuid.UUID | None = None
    all_branches: bool | None = None
    branch_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    status: Literal["active", "disabled"] | None = None


class StaffOut(ApiModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    role_id: uuid.UUID
    role_key: str
    role_name: str
    status: str
    all_branches: bool
    branch_ids: list[uuid.UUID]
    last_login_at: datetime | None
    is_owner: bool
    is_you: bool


# ---------- roles ----------


class PermissionOut(ApiModel):
    key: str
    module: str
    description: str


class RoleIn(ApiModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    permissions: dict[str, Scope] = Field(min_length=1)


class RolePatch(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    permissions: dict[str, Scope] | None = None


class RoleOut(ApiModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    is_system: bool
    permissions: dict[str, str]
    member_count: int
