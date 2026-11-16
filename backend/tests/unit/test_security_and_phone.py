import uuid

import pytest

from app.core.errors import UnauthorizedError
from app.core.phone import normalize_phone
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_otp,
    hash_password,
    verify_password,
)
from app.services.access import TenantContext
from app.services.registration import slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9876543210", "+919876543210"),
        ("098765 43210", "+919876543210"),
        ("+91 98765-43210", "+919876543210"),
        ("0091 9876543210", "+919876543210"),
        ("+14155552671", "+14155552671"),
    ],
)
def test_normalize_phone(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "5876543210", "+91123", "abc", ""])
def test_normalize_phone_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_password_hash_roundtrip() -> None:
    h = hash_password("Str0ng-pass!")
    assert h.startswith("$argon2id$")
    assert verify_password("Str0ng-pass!", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)


def test_access_token_roundtrip_and_tamper() -> None:
    uid, tid = uuid.uuid4(), uuid.uuid4()
    token, _ = create_access_token(uid, is_super_admin=False, tenant_id=tid)
    claims = decode_access_token(token)
    assert claims.user_id == uid and claims.tenant_id == tid and claims.is_super_admin is False
    header, payload, sig = token.split(".")
    with pytest.raises(UnauthorizedError):
        decode_access_token(f"{header}.{payload}.{sig[:-2]}xx")


def test_otp_hash_is_bound_to_phone() -> None:
    assert hash_otp("+919876543210", "123456") != hash_otp("+919876543211", "123456")


@pytest.mark.parametrize(
    ("name", "slug"),
    [("Tales & Spirits", "tales-spirits"), ("  Café Mocha!! ", "cafe-mocha"), ("Urban   Bites", "urban-bites")],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_branch_scoped_permissions() -> None:
    b1, b2 = uuid.uuid4(), uuid.uuid4()
    ctx = TenantContext(
        tenant_id=uuid.uuid4(),
        tenant_name="x",
        tenant_slug="x",
        tenant_status="active",
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        role_key="waiter",
        role_name="Waiter",
        permissions={"tables.operate": "own_branches", "menu.manage": "all"},
        all_branches=False,
        branch_ids=frozenset({b1}),
    )
    assert ctx.can_act_in_branch("tables.operate", b1)
    assert not ctx.can_act_in_branch("tables.operate", b2)
    assert ctx.can_act_in_branch("menu.manage", b2)
    assert not ctx.can_act_in_branch("billing.operate", b1)
