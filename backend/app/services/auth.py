"""Authentication: password login, phone OTP, refresh-token rotation, tenant switching, /me."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import get_settings
from app.core.db import use_system
from app.core.errors import AppError, ForbiddenError, UnauthorizedError
from app.core.phone import normalize_phone
from app.core.security import (
    constant_time_equals,
    create_access_token,
    hash_otp,
    hash_password_async,
    hash_token,
    new_otp_code,
    new_refresh_token,
    password_needs_rehash,
    verify_password_async,
)
from app.models import OtpChallenge, RefreshToken, User
from app.schemas.auth import ActiveTenantOut, MeResponse, OtpSendResponse, UserOut
from app.services.access import (
    list_memberships,
    live_subscription,
    load_tenant_context,
    subscription_out,
    tenant_features,
)
from app.services.audit import write_audit

log = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Invalid email/mobile or password."


@dataclass
class ClientInfo:
    user_agent: str | None
    ip: str | None


@dataclass
class IssuedTokens:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    user: User
    tenant_id: uuid.UUID | None


# ---------- helpers ----------


def _now() -> datetime:
    return datetime.now(UTC)


async def _find_user_by_identifier(session: AsyncSession, identifier: str) -> User | None:
    ident = identifier.strip()
    conditions = [User.email == ident.lower()] if "@" in ident else []
    if "@" not in ident:
        try:
            conditions.append(User.phone == normalize_phone(ident))
        except ValueError:
            return None
    return (await session.execute(select(User).where(or_(*conditions)))).scalar_one_or_none()


async def _default_tenant(session: AsyncSession, user: User) -> uuid.UUID | None:
    memberships = await list_memberships(session, user.id)
    return memberships[0].tenant_id if memberships else None


async def _issue(
    session: AsyncSession,
    user: User,
    client: ClientInfo,
    *,
    tenant_id: uuid.UUID | None,
    family_id: uuid.UUID | None = None,
) -> IssuedTokens:
    s = get_settings()
    raw = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_token(raw),
            tenant_id=tenant_id,
            expires_at=_now() + timedelta(days=s.refresh_token_days),
            user_agent=(client.user_agent or "")[:300] or None,
            ip=client.ip,
        )
    )
    access, exp = create_access_token(user.id, is_super_admin=user.is_super_admin, tenant_id=tenant_id)
    return IssuedTokens(access_token=access, access_expires_at=exp, refresh_token=raw, user=user, tenant_id=tenant_id)


# ---------- password login ----------


async def login_with_password(
    session: AsyncSession, identifier: str, password: str, client: ClientInfo
) -> IssuedTokens:
    key = f"login:{identifier.strip().lower()}"
    await rate_limit.hit(key, limit=5, window_seconds=15 * 60)
    if client.ip:
        await rate_limit.hit(
            f"login-ip:{client.ip}", limit=get_settings().login_ip_limit_per_15min, window_seconds=15 * 60
        )

    await use_system(session)
    user = await _find_user_by_identifier(session, identifier)
    if not await verify_password_async(password, user.password_hash if user else None) or user is None:
        raise UnauthorizedError(INVALID_CREDENTIALS, code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise ForbiddenError("This account is disabled.", code="ACCOUNT_DISABLED")

    if user.password_hash and password_needs_rehash(user.password_hash):
        user.password_hash = await hash_password_async(password)
    user.last_login_at = _now()
    tokens = await _issue(session, user, client, tenant_id=await _default_tenant(session, user))
    await session.commit()
    await rate_limit.reset(key)
    return tokens


# ---------- phone OTP ----------


async def send_otp(session: AsyncSession, phone: str) -> OtpSendResponse:
    s = get_settings()
    await rate_limit.hit(f"otp-send:{phone}", limit=3, window_seconds=10 * 60)
    await use_system(session)
    code = new_otp_code(s.otp_length)
    # Only the latest challenge for a phone is valid.
    await session.execute(
        update(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.consumed_at.is_(None))
        .values(consumed_at=func.now())
    )
    session.add(
        OtpChallenge(
            phone=phone,
            code_hash=hash_otp(phone, code),
            purpose="login",
            expires_at=_now() + timedelta(seconds=s.otp_ttl_seconds),
        )
    )
    await session.commit()
    # SMS provider (Phase 12, SMS_PROVIDER); outside production the code is also logged and returned.
    from app.integrations.messaging import send_otp as deliver

    await deliver(phone, code)
    if s.expose_dev_codes:
        log.info("OTP for %s: %s (development)", phone[:-4] + "****", code)
    return OtpSendResponse(
        phone=phone, expires_in_seconds=s.otp_ttl_seconds, dev_code=code if s.expose_dev_codes else None
    )


async def verify_otp(
    session: AsyncSession, phone: str, code: str, full_name: str | None, client: ClientInfo
) -> IssuedTokens:
    s = get_settings()
    await use_system(session)
    challenge = (
        await session.execute(
            select(OtpChallenge)
            .where(OtpChallenge.phone == phone, OtpChallenge.consumed_at.is_(None))
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if challenge is None or challenge.expires_at <= _now():
        raise AppError("The code has expired. Request a new one.", code="OTP_EXPIRED")
    if challenge.attempts >= s.otp_max_attempts:
        raise AppError("Too many wrong attempts. Request a new code.", code="OTP_LOCKED", status_code=429)

    if not constant_time_equals(challenge.code_hash, hash_otp(phone, code)):
        challenge.attempts += 1
        await session.commit()
        raise AppError("Incorrect code.", code="OTP_INVALID")

    challenge.consumed_at = _now()
    user = (await session.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None:
        user = User(phone=phone, full_name=(full_name or "").strip()[:120], phone_verified_at=_now())
        session.add(user)
        await session.flush()
    else:
        if user.is_super_admin:
            # Platform owner accounts must use their password.
            raise ForbiddenError("Use password login for this account.", code="PASSWORD_LOGIN_REQUIRED")
        if not user.is_active:
            raise ForbiddenError("This account is disabled.", code="ACCOUNT_DISABLED")
        user.phone_verified_at = user.phone_verified_at or _now()
        if full_name and not user.full_name:
            user.full_name = full_name.strip()[:120]
    user.last_login_at = _now()
    tokens = await _issue(session, user, client, tenant_id=await _default_tenant(session, user))
    await session.commit()
    return tokens


# ---------- refresh / logout / switch ----------


async def rotate_refresh_token(
    session: AsyncSession,
    raw_token: str | None,
    client: ClientInfo,
    *,
    tenant_override: uuid.UUID | None = None,
    switch_tenant: bool = False,
    expected_user_id: uuid.UUID | None = None,
) -> IssuedTokens:
    if not raw_token:
        raise UnauthorizedError("Not signed in.", code="NO_REFRESH_TOKEN")
    await use_system(session)
    token = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)).with_for_update()
        )
    ).scalar_one_or_none()
    if token is None:
        raise UnauthorizedError("Session expired. Please sign in again.", code="INVALID_REFRESH_TOKEN")
    if expected_user_id is not None and token.user_id != expected_user_id:
        # Access token and refresh cookie belong to different people: never mix identities.
        raise UnauthorizedError("Session mismatch. Please sign in again.", code="SESSION_MISMATCH")

    if token.revoked_at is not None:
        # A rotated token was presented again → likely stolen. Kill the whole family.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        write_audit(
            session,
            action="auth.refresh_reuse_detected",
            entity="user",
            entity_id=token.user_id,
            actor_user_id=token.user_id,
            ip=client.ip,
        )
        await session.commit()
        raise UnauthorizedError("Session expired. Please sign in again.", code="REFRESH_TOKEN_REUSED")
    if token.expires_at <= _now():
        raise UnauthorizedError("Session expired. Please sign in again.", code="REFRESH_TOKEN_EXPIRED")

    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Session expired. Please sign in again.", code="ACCOUNT_DISABLED")

    tenant_id = tenant_override if switch_tenant else token.tenant_id
    if tenant_id is not None:
        # Membership may have been removed since the token was issued.
        if await load_tenant_context(session, user.id, tenant_id) is None:
            if switch_tenant:
                raise ForbiddenError("You are not a member of that restaurant.", code="NOT_A_MEMBER")
            tenant_id = await _default_tenant(session, user)
        await use_system(session)

    token.revoked_at = _now()
    tokens = await _issue(session, user, client, tenant_id=tenant_id, family_id=token.family_id)
    await session.commit()
    return tokens


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    await use_system(session)
    token = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    ).scalar_one_or_none()
    if token is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        await session.commit()


async def change_password(session: AsyncSession, user: User, current: str, new: str) -> None:
    await rate_limit.hit(f"pwchange:{user.id}", limit=5, window_seconds=15 * 60)
    await use_system(session)
    if not await verify_password_async(current, user.password_hash):
        raise AppError("Current password is incorrect.", code="INVALID_CREDENTIALS")
    user.password_hash = await hash_password_async(new)
    # Sign out other devices.
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    write_audit(session, action="auth.password_changed", entity="user", entity_id=user.id, actor_user_id=user.id)
    await session.commit()


# ---------- /me ----------


async def build_me(session: AsyncSession, user: User, tenant_id: uuid.UUID | None) -> MeResponse:
    memberships = await list_memberships(session, user.id)
    active = None
    if tenant_id is not None:
        ctx = await load_tenant_context(session, user.id, tenant_id)
        if ctx is not None:
            live = await live_subscription(session, ctx.tenant_id)
            features = await tenant_features(session, live[1].id if live else None)
            active = ActiveTenantOut(
                tenant_id=ctx.tenant_id,
                tenant_name=ctx.tenant_name,
                tenant_slug=ctx.tenant_slug,
                tenant_status=ctx.tenant_status,
                role_key=ctx.role_key,
                role_name=ctx.role_name,
                permissions=ctx.permissions,
                all_branches=ctx.all_branches,
                branch_ids=sorted(ctx.branch_ids),
                features=features,
                subscription=subscription_out(*live) if live else None,
            )
    return MeResponse(
        user=UserOut.model_validate(user),
        memberships=memberships,
        active_tenant=active,
    )
