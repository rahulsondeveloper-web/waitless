"""Passwords (Argon2id), JWT access tokens, opaque refresh tokens, OTP codes."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import anyio.to_thread
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errors import UnauthorizedError

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters


# ---------- passwords ----------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # Still spend comparable time so missing accounts are not detectable by timing.
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# Argon2 is deliberately CPU-heavy (~100 ms). In request handlers run it in a worker thread so one
# login never blocks the event loop for every other request.


async def hash_password_async(password: str) -> str:
    return await anyio.to_thread.run_sync(hash_password, password)


async def verify_password_async(password: str, password_hash: str | None) -> bool:
    return await anyio.to_thread.run_sync(verify_password, password, password_hash)


# ---------- access tokens (JWT) ----------


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    is_super_admin: bool
    tenant_id: uuid.UUID | None
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID, *, is_super_admin: bool, tenant_id: uuid.UUID | None
) -> tuple[str, datetime]:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=s.access_token_minutes)
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "sa": is_super_admin,
        "tid": str(tenant_id) if tenant_id else None,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), exp


def decode_access_token(token: str) -> AccessClaims:
    s = get_settings()
    try:
        data = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Session expired.", code="TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid token.", code="INVALID_TOKEN") from exc
    if data.get("typ") != "access":
        raise UnauthorizedError("Invalid token.", code="INVALID_TOKEN")
    try:
        return AccessClaims(
            user_id=uuid.UUID(data["sub"]),
            is_super_admin=bool(data.get("sa")),
            tenant_id=uuid.UUID(data["tid"]) if data.get("tid") else None,
            expires_at=datetime.fromtimestamp(data["exp"], UTC),
        )
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid token.", code="INVALID_TOKEN") from exc


# ---------- refresh tokens (opaque, stored hashed) ----------


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- OTP ----------


def new_otp_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(phone: str, code: str) -> str:
    """Keyed hash so a leaked table cannot be brute-forced offline in seconds."""
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
