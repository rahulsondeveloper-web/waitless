"""Phase 11: plans without code changes, subscriptions & SaaS invoices, overview, content, support desk,
audit log, notification templates, platform settings; restaurant reports and dashboard figures.

Acceptance (test 15): Super Admin creates a new plan with custom limits and assigns it; limits apply immediately.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.core.db import get_sessionmaker
from app.integrations.payments.gateway import MockGateway
from app.services import platform, saas
from tests.conftest import bearer, create_super_admin, login
from tests.integration.test_billing import _order, _serve, _settings
from tests.integration.test_bookings import _setup
from tests.integration.test_operations import _owner, _second_branch
from tests.integration.test_orders import _dish, _join, _seat, _staff

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

SA = "/api/v1/super-admin"
B = "/api/v1/restaurant"


async def _admin(client: httpx.AsyncClient) -> dict[str, str]:
    email = f"sa-{uuid.uuid4().hex[:8]}@waitless.test"
    await create_super_admin(email)
    return bearer(await login(client, email))


def _plan(code: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    return {
        "code": code,
        "name": kw.pop("name", "Growth"),
        "description": "For growing cafés",
        "price_monthly": kw.pop("price_monthly", "999"),
        "price_yearly": "9999",
        "trial_days": 0,
        "features": kw.pop(
            "features",
            [
                {"key": "storefront"},
                {"key": "menu.basic"},
                {"key": "queue"},
                {"key": "tables"},
                {"key": "ordering"},
                {"key": "max_branches", "limit": 2},
                {"key": "max_staff", "limit": 5},
                {"key": "max_tables_per_branch", "limit": 10},
            ],
        ),
        **kw,
    }


async def test_new_plan_with_custom_limits_applies_immediately(client: httpx.AsyncClient) -> None:
    """Acceptance test 15."""
    sa = await _admin(client)
    tenant, h, _ = await _owner(client)
    code = f"growth-{uuid.uuid4().hex[:6]}"
    created = await client.post(f"{SA}/plans", json=_plan(code), headers=sa)
    assert created.status_code == 201, created.text
    plan = created.json()
    assert {f["key"]: f["limit"] for f in plan["features"]}["max_branches"] == 2
    assert (await client.post(f"{SA}/plans", json=_plan(code), headers=sa)).status_code == 409
    bad = await client.post(f"{SA}/plans", json=_plan(f"x{code}", features=[{"key": "teleport"}]), headers=sa)
    assert bad.status_code == 422

    # Professional trial allows 5 branches; the new plan allows 2 — from the moment it is assigned.
    assigned = await client.post(
        f"{SA}/restaurants/{tenant['id']}/subscription",
        json={"plan_id": plan["id"], "billing_cycle": "monthly"},
        headers=sa,
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["plan_code"] == code and assigned.json()["invoices_due"] == 1
    await _second_branch(client, h, "Second")
    third = await client.post(
        f"{B}/branches",
        json={"name": "Third", "address_line": "3 Road Street", "city": "Pune", "state": "MH"},
        headers=h,
    )
    assert third.status_code == 409 and third.json()["error"]["details"]["limit"] == 2
    # Features follow the plan too: no inventory on this plan.
    assert (await client.get(f"{B}/inventory/items", headers=h)).status_code == 402

    # Raising the limit applies at once.
    raised = _plan(code, features=[*_plan(code)["features"][:-3], {"key": "max_branches", "limit": 3}])
    assert (await client.put(f"{SA}/plans/{plan['id']}", json=raised, headers=sa)).status_code == 200
    again = await client.post(
        f"{B}/branches",
        json={"name": "Third", "address_line": "3 Road Street", "city": "Pune", "state": "MH"},
        headers=h,
    )
    assert again.status_code == 201, again.text
    usage = (await client.get(f"{B}/subscription", headers=h)).json()
    assert usage["plan"]["code"] == code
    assert next(x for x in usage["limits"] if x["key"] == "max_branches") == {
        "key": "max_branches",
        "label": "Branches",
        "used": 3,
        "limit": 3,
    }
    plans = (await client.get(f"{SA}/plans/full", headers=sa)).json()
    assert next(p for p in plans if p["code"] == code)["subscribers"] == 1


async def test_subscription_lifecycle_invoices_and_online_payment(client: httpx.AsyncClient) -> None:
    sa = await _admin(client)
    tenant, h, _ = await _owner(client)
    plans = {p["code"]: p for p in (await client.get(f"{SA}/plans/full", headers=sa)).json()}
    pro = plans["professional"]
    await client.put(
        f"{SA}/plans/{pro['id']}",
        json={
            **{
                k: pro[k]
                for k in (
                    "code",
                    "name",
                    "description",
                    "currency",
                    "trial_days",
                    "is_public",
                    "is_active",
                    "sort_order",
                )
            },
            "price_monthly": "1499",
            "price_yearly": "14990",
            "features": pro["features"],
        },
        headers=sa,
    )
    sub = (
        await client.post(f"{SA}/restaurants/{tenant['id']}/subscription", json={"plan_id": pro["id"]}, headers=sa)
    ).json()
    invoices = (await client.get(f"{SA}/saas-invoices", params={"tenant_id": tenant["id"]}, headers=sa)).json()
    first = invoices[0]
    assert first["number"].startswith("WL-") and first["amount"] == "1499.00" and first["tax"] == "269.82"
    assert first["total"] == "1768.82" and first["status"] == "due"

    # The owner pays online (mock gateway → verified webhook).
    pay = await client.post(f"{B}/saas-invoices/{first['id']}/pay", headers=h)
    assert pay.status_code == 200, pay.text
    raw, sig = MockGateway.build_event(pay.json()["order_id"], Decimal("1768.82"), True)
    hook = await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    assert hook.json()["result"] == "paid"
    mine = (await client.get(f"{B}/saas-invoices", headers=h)).json()
    assert mine[0]["status"] == "paid" and mine[0]["payments"][0]["method"] == "gateway"

    # Period ends → renewal invoice, past due; grace ends → expired → paid features stop.
    end = datetime.fromisoformat(sub["current_period_end"].replace("Z", "+00:00"))
    async with get_sessionmaker()() as session:
        counts = await saas.tick(session, now=end + timedelta(minutes=1))
    assert counts["invoiced"] >= 1
    rows = {r["tenant_id"]: r for r in (await client.get(f"{SA}/subscriptions", headers=sa)).json()}
    assert rows[tenant["id"]]["status"] == "past_due" and rows[tenant["id"]]["invoices_due"] == 1
    async with get_sessionmaker()() as session:
        counts = await saas.tick(session, now=end + timedelta(days=8))
    assert counts["expired"] >= 1
    assert (
        await client.get(f"{B}/reservations", params={"branch_id": str(uuid.uuid4())}, headers=h)
    ).status_code == 402

    # Super Admin records a bank transfer for the renewal → active again for that period.
    renewal = next(
        i
        for i in (
            await client.get(f"{SA}/saas-invoices", params={"tenant_id": tenant["id"], "status": "due"}, headers=sa)
        ).json()
    )
    assert renewal["status"] == "due"
    # Expired subscriptions are not revived by an old invoice: assign again, then pay.
    paid = await client.post(
        f"{SA}/saas-invoices/{renewal['id']}/payments", json={"method": "bank", "reference": "UTR123"}, headers=sa
    )
    assert paid.json()["status"] == "paid"
    manual = await client.post(
        f"{SA}/saas-invoices",
        json={"tenant_id": tenant["id"], "amount": "500", "description": "Menu photography"},
        headers=sa,
    )
    assert manual.status_code == 201 and manual.json()["kind"] == "manual"
    voided = await client.post(
        f"{SA}/saas-invoices/{manual.json()['id']}/void", json={"reason": "Sent by mistake"}, headers=sa
    )
    assert voided.json()["status"] == "void"

    extend = await client.post(f"{SA}/subscriptions/{sub['id']}/actions", json={"action": "stop_renewal"}, headers=sa)
    assert extend.json()["auto_renew"] is False

    ov = (await client.get(f"{SA}/overview", headers=sa)).json()
    assert ov["restaurants_total"] >= 1 and Decimal(ov["saas_revenue_total"]) >= Decimal("1768.82")


async def test_content_support_audit_templates_and_settings(client: httpx.AsyncClient) -> None:
    sa = await _admin(client)
    tenant, h, _ = await _owner(client)
    platform.clear_cache()

    saved = await client.put(
        f"{SA}/content/home", json={"title": "Eat on time.", "lead": "WaitLess, everywhere."}, headers=sa
    )
    assert saved.status_code == 200 and saved.json()["title_script"] == "Dine delightfully."  # defaults kept
    public = (await client.get("/api/v1/public/content")).json()
    assert public["home"]["title"] == "Eat on time." and public["terms"]["title"] == "Terms of use"
    assert (await client.put(f"{SA}/content/home", json={"hacker": 1}, headers=sa)).status_code == 422
    assert (await client.put(f"{SA}/content/nope", json={}, headers=sa)).status_code == 404
    assert (await client.put(f"{SA}/content/home", json={"title": "x"}, headers=h)).status_code == 403

    asked = await client.post(
        f"{B}/support", json={"topic": "technical", "message": "The kitchen screen froze twice today."}, headers=h
    )
    assert asked.status_code == 201 and asked.json()["priority"] == "high"
    tickets = (await client.get(f"{SA}/support/tickets", params={"status": "active"}, headers=sa)).json()
    t = next(x for x in tickets if x["tenant_id"] == tenant["id"])
    assert t["source"] == "restaurant" and t["tenant_name"]
    admins = (await client.get(f"{SA}/admins", headers=sa)).json()
    upd = await client.patch(
        f"{SA}/support/tickets/{t['id']}",
        json={"status": "in_progress", "assigned_to_id": str(admins[0]["id"])},
        headers=sa,
    )
    assert upd.json()["status"] == "in_progress" and upd.json()["assigned_to_name"]
    noted = await client.post(
        f"{SA}/support/tickets/{t['id']}/notes", json={"body": "Asked for a screenshot."}, headers=sa
    )
    assert noted.json()["notes"][0]["body"] == "Asked for a screenshot."
    mine = (await client.get(f"{B}/support", headers=h)).json()
    assert mine[0]["status"] == "in_progress" and mine[0]["notes"] is None  # internal notes stay internal

    log = (await client.get(f"{SA}/audit", params={"admins_only": True, "action": "support"}, headers=sa)).json()
    assert log["total"] >= 1 and log["items"][0]["actor_is_admin"] is True
    by_tenant = (await client.get(f"{SA}/audit", params={"tenant_id": tenant["id"]}, headers=sa)).json()
    assert all(i["tenant_id"] == tenant["id"] for i in by_tenant["items"])

    tpl = await client.put(
        f"{SA}/notification-templates/queue.table_ready",
        json={"title": "{title} 🎉", "body": "{body} Show this at the door.", "enabled": True},
        headers=sa,
    )
    assert next(x for x in tpl.json() if x["event"] == "queue.table_ready")["customised"] is True
    platform._tpl_cache["at"] = 0.0
    assert await platform.render("queue.table_ready", "Table ready", "Come in.") == (
        "Table ready 🎉",
        "Come in. Show this at the door.",
    )
    await client.put(
        f"{SA}/notification-templates/order.ready", json={"title": "x", "body": "y", "enabled": False}, headers=sa
    )
    platform._tpl_cache["at"] = 0.0
    assert await platform.render("order.ready", "a", "b") is None
    broken = await client.put(f"{SA}/notification-templates/order.ready", json={"title": "{", "body": "y"}, headers=sa)
    assert broken.status_code == 422

    st = await client.put(f"{SA}/settings", json={"allow_registration": False, "grace_days": 3}, headers=sa)
    assert st.json()["settings"]["grace_days"] == 3 and st.json()["integrations"][0]["name"] == "Payments"
    from tests.conftest import registration_payload

    closed = await client.post("/api/v1/public/restaurants/register", json=registration_payload())
    assert closed.status_code == 403 and closed.json()["error"]["code"] == "REGISTRATION_CLOSED"
    assert (await client.put(f"{SA}/settings", json={"bogus": 1}, headers=sa)).status_code == 422


async def test_reports_dashboard_and_permissions(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    await _settings(client, h, round_off=False)
    dish = await _dish(client, h, "Veg Biryani", "300", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    o = await _order(client, t, (dish, 2))
    await _serve(client, h, o)
    bill = (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=h)).json()["bills"][0]
    await client.post(
        f"{B}/bills/{bill['id']}/payments", json={"method": "upi", "amount": bill["grand_total"]}, headers=h
    )

    dash = (await client.get(f"{B}/dashboard", headers=h)).json()
    assert dash["todays_revenue"] == "630.00" and dash["discounts_today"] == "0.00"
    assert dash["average_serving_minutes"] == 0 and dash["delayed_orders"] == 0

    sales = (await client.get(f"{B}/reports/sales", params={"branch_id": branch["id"]}, headers=h)).json()
    assert sales["totals"]["Net revenue"] == "630.00" and sales["totals"]["Bills"] == "1"
    assert sales["chart"]["type"] == "bar" and len(sales["chart"]["labels"]) == 14
    pays = (await client.get(f"{B}/reports/payments", headers=h)).json()
    assert pays["rows"] == [["UPI", 1, "630.00", "0.00", "630.00"]]
    for kind in ("orders", "serving", "discounts", "reservations", "queue"):
        assert (await client.get(f"{B}/reports/{kind}", headers=h)).status_code == 200, kind
    # Professional has basic analytics only.
    assert (await client.get(f"{B}/reports/top_items", headers=h)).status_code == 402
    waiter = await _staff(client, h, branch, "waiter")
    assert (await client.get(f"{B}/reports/sales", headers=waiter)).status_code == 403
    assert (await client.get(f"{B}/reports/nope", headers=h)).status_code == 404
    limits = await client.put(
        f"{B}/settings/limits", json={"manual_discount_pct": "15", "refund_amount": "5000"}, headers=h
    )
    assert limits.json()["manual_discount_pct"] == "15"
    _ = datetime.now(UTC)
