"""Import every model module here so Alembic autogenerate sees all tables."""

from app.models.base import Base
from app.models.identity import OtpChallenge, RefreshToken, User
from app.models.platform import AuditLog, IdempotencyKey, OutboxEvent
from app.models.saas import Plan, PlanFeature, Subscription
from app.models.tenancy import Branch, Membership, Permission, Role, RolePermission, Tenant, UserBranch

__all__ = [
    "AuditLog",
    "Base",
    "Branch",
    "IdempotencyKey",
    "Membership",
    "OtpChallenge",
    "OutboxEvent",
    "Permission",
    "Plan",
    "PlanFeature",
    "RefreshToken",
    "Role",
    "RolePermission",
    "Subscription",
    "Tenant",
    "User",
    "UserBranch",
]
