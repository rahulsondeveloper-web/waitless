"""Plan limits (docs/04 §4): max_branches, max_staff, max_tables_per_branch, …"""

import uuid

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError
from app.services.access import live_subscription, tenant_features


async def enforce_limit(session: AsyncSession, tenant_id: uuid.UUID, feature: str, current: int, label: str) -> None:
    """Raise 409 PLAN_LIMIT_REACHED when adding one more would exceed the plan. NULL limit = unlimited."""
    live = await live_subscription(session, tenant_id)
    if live is None:
        raise AppError(
            "Your WaitLess plan is not active.", code="NO_ACTIVE_PLAN", status_code=status.HTTP_402_PAYMENT_REQUIRED
        )
    feat = (await tenant_features(session, live[1].id)).get(feature)
    if feat is not None and feat.limit is not None and current >= feat.limit:
        raise ConflictError(
            f"Your {live[1].name} plan allows {feat.limit} {label}. Upgrade to add more.",
            code="PLAN_LIMIT_REACHED",
            details={"feature": feature, "limit": feat.limit, "plan": live[1].code},
        )
