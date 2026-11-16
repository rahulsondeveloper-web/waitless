"""PRD §4 registration and §16 Super Admin lifecycle. Covers PRD test scenarios 1, 2 and 15 (partly)."""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import bearer, create_super_admin, login, register, registration_payload

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]


async def test_registration_creates_everything_in_prd_order(
    client: httpx.AsyncClient, admin_engine: AsyncEngine
) -> None:
    tenant, payload = await register(client, restaurant_name="Tales & Spirits", city="Mumbai")
    assert tenant["status"] == "pending"
    assert tenant["slug"] == "tales-spirits"
    assert tenant["is_published"] is False

    auth = await login(client, payload["email"])
    active = auth["me"]["active_tenant"]
    assert active["tenant_id"] == tenant["id"]
    assert active["role_key"] == "owner"
    assert active["all_branches"] is True
    assert "restaurant.branding.manage" in active["permissions"]
    assert active["subscription"]["status"] == "trialing"
    assert active["subscription"]["plan_code"] == "professional"
    assert active["features"]["inventory"]["enabled"] is True

    me = await client.get("/api/v1/restaurant/me", headers=bearer(auth))
    assert me.status_code == 200
    branches = me.json()["branches"]
    assert len(branches) == 1 and branches[0]["is_primary"] and branches[0]["city"] == "Mumbai"

    async with admin_engine.connect() as conn:
        settings = (
            await conn.execute(text("SELECT settings FROM tenants WHERE id = :id"), {"id": tenant["id"]})
        ).scalar_one()
        audit = (
            await conn.execute(
                text("SELECT count(*) FROM audit_logs WHERE entity_id = :id AND action = 'restaurant.registered'"),
                {"id": tenant["id"]},
            )
        ).scalar_one()
        outbox = (
            await conn.execute(text("SELECT count(*) FROM outbox_events WHERE event = 'restaurant.registered'"))
        ).scalar_one()
    assert settings["serving_promise"]["serving_minutes"] == 15
    assert audit == 1 and outbox == 1


async def test_slug_collisions_get_city_then_number(client: httpx.AsyncClient) -> None:
    a, _ = await register(client, restaurant_name="Spice Route", city="Pune")
    b, _ = await register(client, restaurant_name="Spice Route", city="Pune")
    c, _ = await register(client, restaurant_name="Spice Route", city="Pune")
    assert [a["slug"], b["slug"], c["slug"]] == ["spice-route", "spice-route-pune", "spice-route-2"]

    r = await client.get("/api/v1/public/slug-availability", params={"slug": "Spice Route"})
    assert r.json() == {"slug": "spice-route", "available": False, "suggestion": "spice-route-3"}


async def test_reserved_and_taken_slugs_are_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/public/restaurants/register", json=registration_payload(preferred_slug="super-admin")
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "SLUG_TAKEN"


async def test_duplicate_email_or_mobile_is_rejected(client: httpx.AsyncClient) -> None:
    _, payload = await register(client)
    r = await client.post("/api/v1/public/restaurants/register", json=registration_payload(email=payload["email"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"
    r = await client.post("/api/v1/public/restaurants/register", json=registration_payload(mobile=payload["mobile"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "PHONE_TAKEN"


async def test_registration_validation(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/public/restaurants/register",
        json=registration_payload(mobile="12345", password="short", cuisines=[]),
    )
    assert r.status_code == 422
    fields = {tuple(e["loc"]) for e in r.json()["error"]["details"]["errors"]}
    assert {("body", "mobile"), ("body", "password"), ("body", "cuisines")} <= fields


async def test_super_admin_registers_and_activates_restaurant(
    client: httpx.AsyncClient, admin_engine: AsyncEngine
) -> None:
    """PRD test 1 + 2: Super Admin registers and activates a restaurant; owner logs in."""
    await create_super_admin()
    admin = bearer(await login(client, "admin@waitless.test"))

    created = await client.post("/api/v1/super-admin/restaurants", json=registration_payload(), headers=admin)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["status"] == "pending" and row["owner"]["full_name"] == "Asha Owner" and row["city"] == "Pune"

    pending = await client.get("/api/v1/super-admin/restaurants", params={"status": "pending"}, headers=admin)
    assert pending.json()["total"] == 1

    approved = await client.patch(
        f"/api/v1/super-admin/restaurants/{row['id']}/status", json={"action": "approve"}, headers=admin
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active" and approved.json()["approved_at"]

    owner = await login(client, row["owner"]["email"])
    assert owner["me"]["active_tenant"]["tenant_status"] == "active"

    async with admin_engine.connect() as conn:
        actions = (
            (
                await conn.execute(
                    text("SELECT action FROM audit_logs WHERE entity_id = :id ORDER BY created_at"), {"id": row["id"]}
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["restaurant.registered", "restaurant.approve"]


async def test_status_rules_reason_and_transitions(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    admin = bearer(await login(client, "admin@waitless.test"))
    tenant, payload = await register(client)
    url = f"/api/v1/super-admin/restaurants/{tenant['id']}/status"

    bad = await client.patch(url, json={"action": "suspend", "reason": "x"}, headers=admin)
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    no_reason = await client.patch(url, json={"action": "reject"}, headers=admin)
    assert no_reason.status_code == 422 and no_reason.json()["error"]["code"] == "REASON_REQUIRED"

    assert (await client.patch(url, json={"action": "approve"}, headers=admin)).status_code == 200
    suspended = await client.patch(url, json={"action": "suspend", "reason": "Unpaid invoice"}, headers=admin)
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["status_reason"] == "Unpaid invoice"

    # Suspended restaurant: operational endpoints blocked, status page still opens.
    owner = bearer(await login(client, payload["email"]))
    blocked = await client.get("/api/v1/restaurant/branches", headers=owner)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "TENANT_INACTIVE"
    me = await client.get("/api/v1/restaurant/me", headers=owner)
    assert me.status_code == 200 and me.json()["tenant"]["status"] == "suspended"

    assert (await client.patch(url, json={"action": "activate"}, headers=admin)).json()["status"] == "active"
    assert (await client.get("/api/v1/restaurant/branches", headers=owner)).status_code == 200


async def test_super_admin_endpoints_require_super_admin(client: httpx.AsyncClient) -> None:
    _, payload = await register(client)
    owner = bearer(await login(client, payload["email"]))
    r = await client.get("/api/v1/super-admin/restaurants", headers=owner)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SUPER_ADMIN_REQUIRED"
    assert (await client.get("/api/v1/super-admin/restaurants")).status_code == 401


async def test_plans_are_seeded(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    admin = bearer(await login(client, "admin@waitless.test"))
    codes = [p["code"] for p in (await client.get("/api/v1/super-admin/plans", headers=admin)).json()]
    assert codes == ["starter", "professional", "enterprise"]
