"""PRD test 16: unauthorised users cannot access other tenants — checked at API level AND database (RLS) level."""

import uuid

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker, use_system, use_tenant
from app.models import Branch, Membership, Role, Tenant
from tests.conftest import bearer, login, random_mobile, register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]


async def _two_restaurants(client: httpx.AsyncClient):  # type: ignore[no-untyped-def]
    a, pa = await register(client, restaurant_name="Alpha Kitchen")
    b, pb = await register(client, restaurant_name="Beta Bistro")
    owner_a = bearer(await login(client, pa["email"]))
    owner_b = bearer(await login(client, pb["email"]))
    return a, b, owner_a, owner_b


async def test_api_owner_cannot_read_other_tenants_records(client: httpx.AsyncClient) -> None:
    a, b, owner_a, owner_b = await _two_restaurants(client)

    a_branches = (await client.get("/api/v1/restaurant/branches", headers=owner_a)).json()
    b_branches = (await client.get("/api/v1/restaurant/branches", headers=owner_b)).json()
    assert len(a_branches) == 1 and len(b_branches) == 1
    assert a_branches[0]["id"] != b_branches[0]["id"]

    # A asks for B's branch by id → 404 (not 403: existence is not revealed).
    r = await client.get(f"/api/v1/restaurant/branches/{b_branches[0]['id']}", headers=owner_a)
    assert r.status_code == 404
    # Own branch works.
    assert (await client.get(f"/api/v1/restaurant/branches/{a_branches[0]['id']}", headers=owner_a)).status_code == 200


async def test_api_cannot_switch_into_a_foreign_tenant(client: httpx.AsyncClient) -> None:
    a, pa = await register(client, restaurant_name="Alpha Kitchen")
    b, _ = await register(client, restaurant_name="Beta Bistro")
    owner_a = bearer(await login(client, pa["email"]))  # cookie jar now holds A's refresh token
    r = await client.post("/api/v1/auth/switch-tenant", json={"tenant_id": b["id"]}, headers=owner_a)
    assert r.status_code == 403 and r.json()["error"]["code"] == "NOT_A_MEMBER"


async def test_switch_tenant_rejects_someone_elses_refresh_cookie(client: httpx.AsyncClient) -> None:
    a, b, owner_a, _ = await _two_restaurants(client)  # cookie jar holds B's refresh token (last login)
    r = await client.post("/api/v1/auth/switch-tenant", json={"tenant_id": a["id"]}, headers=owner_a)
    assert r.status_code == 401 and r.json()["error"]["code"] == "SESSION_MISMATCH"


async def test_customer_without_membership_has_no_tenant_access(client: httpx.AsyncClient) -> None:
    await _two_restaurants(client)
    mobile = random_mobile()
    code = (await client.post("/api/v1/auth/otp/send", json={"phone": mobile})).json()["dev_code"]
    customer = (await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code})).json()
    r = await client.get("/api/v1/restaurant/branches", headers=bearer(customer))
    assert r.status_code == 403 and r.json()["error"]["code"] == "NO_ACTIVE_TENANT"


async def test_rls_hides_other_tenants_even_without_where_clause(client: httpx.AsyncClient) -> None:
    a, b, _, _ = await _two_restaurants(client)
    async with get_sessionmaker()() as session:  # connects as the non-owner app role
        await use_tenant(session, uuid.UUID(a["id"]))
        tenant_ids = {row.tenant_id for row in (await session.execute(select(Branch))).scalars()}
        assert tenant_ids == {uuid.UUID(a["id"])}
        visible_tenants = {t.id for t in (await session.execute(select(Tenant))).scalars()}
        assert visible_tenants == {uuid.UUID(a["id"])}  # B is pending/unpublished → invisible

        # No tenant and no bypass → nothing at all.
        await use_tenant(session, None)
        assert (await session.execute(select(Branch))).scalars().all() == []
        await session.rollback()


async def test_rls_blocks_writing_rows_for_another_tenant(client: httpx.AsyncClient) -> None:
    a, b, _, _ = await _two_restaurants(client)
    async with get_sessionmaker()() as session:
        await use_tenant(session, uuid.UUID(a["id"]))
        session.add(
            Branch(tenant_id=uuid.UUID(b["id"]), name="Sneaky", address_line="x", city="x", state="x", country="x")
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.flush()
        await session.rollback()


async def test_rls_blocks_updating_another_tenants_rows(client: httpx.AsyncClient) -> None:
    a, b, _, _ = await _two_restaurants(client)
    async with get_sessionmaker()() as session:
        await use_tenant(session, uuid.UUID(a["id"]))
        result = await session.execute(text("UPDATE branches SET name = 'hacked' WHERE tenant_id = :b"), {"b": b["id"]})
        assert result.rowcount == 0
        await session.rollback()


async def test_membership_cannot_use_another_tenants_role(client: httpx.AsyncClient) -> None:
    a, b, _, _ = await _two_restaurants(client)
    async with get_sessionmaker()() as session:
        await use_system(session)
        foreign_role = Role(tenant_id=uuid.UUID(b["id"]), key="host", name="Host")
        session.add(foreign_role)
        await session.flush()
        owner_a = (
            await session.execute(select(Membership).where(Membership.tenant_id == uuid.UUID(a["id"])))
        ).scalar_one()
        session.add(Membership(tenant_id=uuid.UUID(a["id"]), user_id=owner_a.user_id, role_id=foreign_role.id))
        with pytest.raises(DBAPIError, match="does not belong to tenant"):
            await session.flush()
        await session.rollback()


async def test_app_role_is_not_privileged(client: httpx.AsyncClient) -> None:
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))
        ).one()
        assert tuple(row) == (False, False)
