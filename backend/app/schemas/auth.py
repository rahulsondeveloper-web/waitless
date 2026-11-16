import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel, Password, PhoneNumber


class LoginRequest(ApiModel):
    identifier: str = Field(min_length=3, max_length=254, description="Email or mobile number")
    password: str = Field(min_length=1, max_length=128)


class OtpSendRequest(ApiModel):
    phone: PhoneNumber


class OtpSendResponse(ApiModel):
    phone: str
    expires_in_seconds: int
    dev_code: str | None = Field(
        default=None, description="Only outside production, until an SMS provider is configured."
    )


class OtpVerifyRequest(ApiModel):
    phone: PhoneNumber
    code: str = Field(pattern=r"^\d{4,8}$")
    full_name: str | None = Field(default=None, max_length=120)


class SwitchTenantRequest(ApiModel):
    tenant_id: uuid.UUID | None


class ChangePasswordRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password


class UserOut(ApiModel):
    id: uuid.UUID
    full_name: str
    email: str | None  # validated on input; output must never fail on stored data
    phone: str | None
    is_super_admin: bool


class FeatureOut(ApiModel):
    enabled: bool
    limit: int | None


class SubscriptionOut(ApiModel):
    plan_code: str
    plan_name: str
    status: str
    trial_ends_at: datetime | None
    current_period_end: datetime


class MembershipOut(ApiModel):
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_slug: str
    tenant_status: str
    role_key: str
    role_name: str


class ActiveTenantOut(MembershipOut):
    permissions: dict[str, str]  # permission key -> scope ("all" | "own_branches")
    all_branches: bool
    branch_ids: list[uuid.UUID]
    features: dict[str, FeatureOut]
    subscription: SubscriptionOut | None


class MeResponse(ApiModel):
    user: UserOut
    memberships: list[MembershipOut]
    active_tenant: ActiveTenantOut | None


class AuthResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    me: MeResponse
