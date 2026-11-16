"""Who may do what, where: tenant context, memberships, plan features."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system, use_tenant
from app.models import Membership, Plan, PlanFeature, Role, RolePermission, Subscription, Tenant, UserBranch
from app.models.saas import LIVE_SUBSCRIPTION_STATUSES
from app.schemas.auth import FeatureOut, MembershipOut, SubscriptionOut

ACTIVE_TENANT_STATUSES = ("pending", "active")  # pending: owner can set up the restaurant before approval


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_slug: str
    tenant_status: str
    user_id: uuid.UUID
    membership_id: uuid.UUID
    role_key: str
    role_name: str
    permissions: dict[str, str]  # key -> scope
    all_branches: bool
    branch_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def can_act_in_branch(self, permission: str, branch_id: uuid.UUID) -> bool:
        scope = self.permissions.get(permission)
        if scope is None:
            return False
        return scope == "all" or self.all_branches or branch_id in self.branch_ids


async def load_tenant_context(session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID) -> TenantContext | None:
    """Scope the session to `tenant_id` and load the user's membership there (None if not a member)."""
    await use_tenant(session, tenant_id)
    row = (
        await session.execute(
            select(Membership, Role, Tenant)
            .join(Role, Role.id == Membership.role_id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(Membership.user_id == user_id, Membership.tenant_id == tenant_id, Membership.status == "active")
        )
    ).first()
    if row is None:
        return None
    membership, role, tenant = row
    perms = dict(
        (
            await session.execute(
                select(RolePermission.permission_key, RolePermission.scope).where(RolePermission.role_id == role.id)
            )
        )
        .tuples()
        .all()
    )
    branch_ids = frozenset(
        (await session.execute(select(UserBranch.branch_id).where(UserBranch.membership_id == membership.id)))
        .scalars()
        .all()
    )
    return TenantContext(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        tenant_status=tenant.status,
        user_id=user_id,
        membership_id=membership.id,
        role_key=role.key,
        role_name=role.name,
        permissions=perms,
        all_branches=membership.all_branches,
        branch_ids=branch_ids,
    )


async def list_memberships(session: AsyncSession, user_id: uuid.UUID) -> list[MembershipOut]:
    """All restaurants a user works for. Cross-tenant by nature → system context."""
    await use_system(session)
    rows = await session.execute(
        select(Membership, Role, Tenant)
        .join(Role, Role.id == Membership.role_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(Membership.user_id == user_id, Membership.status == "active")
        .order_by(Membership.created_at)
    )
    return [
        MembershipOut(
            tenant_id=t.id,
            tenant_name=t.name,
            tenant_slug=t.slug,
            tenant_status=t.status,
            role_key=r.key,
            role_name=r.name,
        )
        for _, r, t in rows.tuples()
    ]


async def live_subscription(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[Subscription, Plan] | None:
    row = (
        await session.execute(
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.tenant_id == tenant_id, Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
        )
    ).first()
    return (row[0], row[1]) if row else None


def subscription_out(sub: Subscription, plan: Plan) -> SubscriptionOut:
    return SubscriptionOut(
        plan_code=plan.code,
        plan_name=plan.name,
        status=sub.status,
        trial_ends_at=sub.trial_ends_at,
        current_period_end=sub.current_period_end,
    )


async def tenant_features(session: AsyncSession, plan_id: uuid.UUID | None) -> dict[str, FeatureOut]:
    if plan_id is None:
        return {}
    rows = await session.execute(
        select(PlanFeature.feature_key, PlanFeature.enabled, PlanFeature.limit_value).where(
            PlanFeature.plan_id == plan_id
        )
    )
    return {key: FeatureOut(enabled=enabled, limit=limit) for key, enabled, limit in rows.tuples()}
