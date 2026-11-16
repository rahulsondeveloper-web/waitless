"""Shared FastAPI dependencies: session, current user, tenant context, permissions, plan features."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session, use_system
from app.core.errors import AppError, ForbiddenError, UnauthorizedError
from app.core.security import AccessClaims, decode_access_token
from app.models import User
from app.services.access import ACTIVE_TENANT_STATUSES, TenantContext, live_subscription, load_tenant_context
from app.services.auth import ClientInfo

SessionDep = Annotated[AsyncSession, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login or /auth/otp/verify")


def client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )


ClientDep = Annotated[ClientInfo, Depends(client_info)]


async def get_claims(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> AccessClaims:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("Please sign in.", code="NOT_AUTHENTICATED")
    return decode_access_token(creds.credentials)


ClaimsDep = Annotated[AccessClaims, Depends(get_claims)]


async def get_current_user(session: SessionDep, claims: ClaimsDep) -> User:
    user = await session.get(User, claims.user_id)  # users is a platform table (no RLS)
    if user is None or not user.is_active:
        raise UnauthorizedError("Please sign in again.", code="ACCOUNT_DISABLED")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_super_admin(session: SessionDep, user: CurrentUser, claims: ClaimsDep) -> User:
    if not (user.is_super_admin and claims.is_super_admin):
        raise ForbiddenError("Super Admin access required.", code="SUPER_ADMIN_REQUIRED")
    await use_system(session)
    return user


SuperAdmin = Annotated[User, Depends(require_super_admin)]


async def _tenant_context(
    session: AsyncSession, user: User, claims: AccessClaims, *, allow_inactive: bool
) -> TenantContext:
    if claims.tenant_id is None:
        raise ForbiddenError("Select a restaurant first.", code="NO_ACTIVE_TENANT")
    ctx = await load_tenant_context(session, user.id, claims.tenant_id)
    if ctx is None:
        raise ForbiddenError("You are not a member of this restaurant.", code="NOT_A_MEMBER")
    if not allow_inactive and ctx.tenant_status not in ACTIVE_TENANT_STATUSES:
        raise ForbiddenError(
            "This restaurant is not active on WaitLess.",
            code="TENANT_INACTIVE",
            details={"status": ctx.tenant_status},
        )
    return ctx


async def tenant_context(session: SessionDep, user: CurrentUser, claims: ClaimsDep) -> TenantContext:
    return await _tenant_context(session, user, claims, allow_inactive=False)


async def tenant_context_any_status(session: SessionDep, user: CurrentUser, claims: ClaimsDep) -> TenantContext:
    """For pages that must still open when the restaurant is suspended (e.g. to show why)."""
    return await _tenant_context(session, user, claims, allow_inactive=True)


TenantCtx = Annotated[TenantContext, Depends(tenant_context)]
TenantCtxAnyStatus = Annotated[TenantContext, Depends(tenant_context_any_status)]


def require_permission(permission: str) -> Callable[..., Awaitable[TenantContext]]:
    async def checker(ctx: TenantCtx) -> TenantContext:
        if not ctx.has(permission):
            raise ForbiddenError(
                "You do not have permission to do this.",
                code="PERMISSION_DENIED",
                details={"permission": permission},
            )
        return ctx

    return checker


def require_feature(feature: str) -> Callable[..., Awaitable[TenantContext]]:
    """Plan gate (docs/04 §4): 402 when the tenant's plan does not include the feature."""

    async def checker(session: SessionDep, ctx: TenantCtx) -> TenantContext:
        from app.services.access import tenant_features  # local: avoid cycles at import time

        live = await live_subscription(session, ctx.tenant_id)
        features = await tenant_features(session, live[1].id if live else None)
        f = features.get(feature)
        if f is None or not f.enabled:
            raise AppError(
                "Your plan does not include this feature.",
                code="PLAN_FEATURE_REQUIRED",
                status_code=402,
                details={"feature": feature},
            )
        return ctx

    return checker
