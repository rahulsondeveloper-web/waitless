"""Phase 12 security review: tenant isolation sweep, at three levels (complements test_tenant_isolation.py).

1. Catalogue: every table with a tenant_id has Row-Level Security enabled, FORCED and a policy
   (only the documented platform-internal tables are exempt).
2. Database: connected as the application role inside restaurant B, no row of restaurant A is visible
   in any of those tables, and writing a row for A is rejected.
3. API: restaurant B's staff get 404/403 — never data — for every kind of restaurant-A identifier.
"""

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from tests.integration.test_billing import _order, _serve
from tests.integration.test_bookings import _setup
from tests.integration.test_inventory import _item, _move
from tests.integration.test_orders import _dish, _join, _seat

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
EXEMPT = {"refresh_tokens", "outbox_events"}  # identity / delivery internals, system scope only


async def _tenant_tables(conn) -> dict[str, tuple[bool, bool, bool]]:  # type: ignore[no-untyped-def]
    rows = await conn.execute(
        text(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public' AND p.tablename = c.relname)
            FROM information_schema.columns col
            JOIN pg_class c ON c.relname = col.table_name AND c.relkind = 'r'
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            WHERE col.table_schema = 'public' AND col.column_name = 'tenant_id'
            """
        )
    )
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


async def test_every_tenant_table_has_forced_rls(admin_engine) -> None:  # type: ignore[no-untyped-def]
    async with admin_engine.connect() as conn:
        tables = await _tenant_tables(conn)
    assert len(tables) > 50
    missing = sorted(t for t, flags in tables.items() if t not in EXEMPT and not all(flags))
    assert missing == [], f"tables without enabled+forced RLS and a policy: {missing}"


async def _seed_restaurant(client: httpx.AsyncClient, name: str) -> dict:
    tenant, h, branch, tables = await _setup(client, name=name)
    dish = await _dish(client, h, f"{name} Thali", "250", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    order = await _order(client, t, (dish, 2))
    await _serve(client, h, order)
    bill = (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=h)).json()["bills"][0]
    paid = (
        await client.post(
            f"{B}/bills/{bill['id']}/payments", json={"method": "card", "amount": bill["grand_total"]}, headers=h
        )
    ).json()
    item = await _item(client, h, f"{name} Rice", "kg", purchase_price="80")
    await _move(client, h, branch, item, "opening", "10")
    supplier = (await client.post(f"{B}/suppliers", json={"name": f"{name} Supplies"}, headers=h)).json()
    purchase = (
        await client.post(
            f"{B}/purchases",
            json={
                "branch_id": branch["id"],
                "supplier_id": supplier["id"],
                "items": [{"item_id": item["id"], "quantity": "1", "unit_price": "80"}],
            },
            headers=h,
        )
    ).json()
    await client.post(
        f"{B}/support", json={"topic": "general", "message": f"{name} needs help with the menu."}, headers=h
    )
    return {
        "tenant": tenant,
        "h": h,
        "branch": branch,
        "table": tables["T1"],
        "session": seated["session"],
        "dish": dish,
        "order": order,
        "bill": paid,
        "invoice": paid["invoices"][0],
        "payment": paid["payments"][0],
        "item": item,
        "supplier": supplier,
        "purchase": purchase,
    }


async def test_database_never_shows_or_accepts_another_restaurants_rows(
    client: httpx.AsyncClient, admin_engine
) -> None:  # type: ignore[no-untyped-def]
    a = await _seed_restaurant(client, "Alpha Diner")
    b = await _seed_restaurant(client, "Beta Bistro")
    a_id, b_id = a["tenant"]["id"], b["tenant"]["id"]
    async with admin_engine.connect() as conn:
        tables = [t for t in await _tenant_tables(conn) if t not in EXEMPT]
        # Sanity: restaurant A really has rows (as the owner role, which bypasses RLS).
        assert (
            await conn.execute(text("SELECT count(*) FROM orders WHERE tenant_id = :t"), {"t": a_id})
        ).scalar_one() >= 1

    app_engine = create_async_engine(get_settings().database_url(test=True))  # the application role
    try:
        async with app_engine.connect() as conn:
            await conn.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": b_id})
            leaks = {}
            for table in tables:
                n = (
                    await conn.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": a_id})
                ).scalar_one()
                if n:
                    leaks[table] = n
            assert leaks == {}, f"restaurant A visible from restaurant B: {leaks}"
            own = (await conn.execute(text("SELECT count(*) FROM orders"))).scalar_one()
            assert own >= 1  # B still sees its own data
            # Without any tenant set, nothing at all is visible.
            await conn.execute(text("SELECT set_config('app.tenant_id', '', false)"))
            assert (await conn.execute(text("SELECT count(*) FROM bills"))).scalar_one() == 0
            await conn.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": b_id})
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "INSERT INTO inventory_categories (id, tenant_id, name, sort_order)"
                        " VALUES (:i, :t, 'Stolen', 0)"
                    ),
                    {"i": str(uuid.uuid4()), "t": a_id},
                )
    finally:
        await app_engine.dispose()


async def test_api_never_returns_another_restaurants_data(client: httpx.AsyncClient) -> None:
    a = await _seed_restaurant(client, "Gamma Grill")
    b = await _seed_restaurant(client, "Delta Dhaba")
    h = b["h"]  # restaurant B's owner tries restaurant A's identifiers
    probes = [
        ("GET", f"/branches/{a['branch']['id']}"),
        ("PATCH", f"/tables/{a['table']['id']}/status", {"status": "cleaning"}),
        ("POST", f"/table-sessions/{a['session']['id']}/bill", {}),
        ("POST", f"/table-sessions/{a['session']['id']}/close", {}),
        ("POST", f"/orders/{a['order']['id']}/status", {"status": "accepted"}),
        ("POST", f"/orders/{a['order']['id']}/cancel", {"reason": "x"}),
        ("GET", f"/bills/{a['bill']['id']}"),
        ("POST", f"/bills/{a['bill']['id']}/discount", {"pct": "50", "reason": "x"}),
        ("POST", f"/payments/{a['payment']['id']}/refunds", {"amount": "1", "reason": "x"}),
        ("GET", f"/invoices/{a['invoice']['id']}"),
        ("GET", f"/invoices/{a['invoice']['id']}/pdf"),
        ("PATCH", f"/menu/items/{a['dish']['id']}", {"name": "Hacked"}),
        ("GET", f"/menu/items/{a['dish']['id']}/recipe"),
        ("PUT", f"/inventory/items/{a['item']['id']}", {"name": "x", "unit": "kg"}),
        (
            "POST",
            "/inventory/movements",
            {
                "branch_id": a["branch"]["id"],
                "item_id": a["item"]["id"],
                "type": "wastage",
                "quantity": "1",
                "reason": "x",
            },
        ),
        ("GET", "/inventory/stock", None, {"branch_id": a["branch"]["id"]}),
        ("GET", "/orders", None, {"branch_id": a["branch"]["id"]}),
        ("GET", "/billing/tables", None, {"branch_id": a["branch"]["id"]}),
        ("GET", "/reports/sales", None, {"branch_id": a["branch"]["id"]}),
        ("PUT", f"/suppliers/{a['supplier']['id']}", {"name": "x"}),
        ("POST", f"/purchases/{a['purchase']['id']}/receive", {}),
    ]
    leaks = []
    for probe in probes:
        method, path = probe[0], probe[1]
        body = probe[2] if len(probe) > 2 else None
        params = probe[3] if len(probe) > 3 else None
        r = await client.request(method, f"{B}{path}", json=body, params=params, headers=h)
        if r.status_code < 400 or r.status_code in (500, 502):
            leaks.append((method, path, r.status_code))
    assert leaks == [], f"cross-restaurant access: {leaks}"

    # Lists only ever contain the caller's own rows.
    own_ids = {
        "orders": {
            o["id"]
            for o in (
                await client.get(f"{B}/orders", params={"branch_id": b["branch"]["id"], "active": False}, headers=h)
            ).json()
        },
        "items": {i["id"] for i in (await client.get(f"{B}/inventory/items", headers=h)).json()},
        "suppliers": {s["id"] for s in (await client.get(f"{B}/suppliers", headers=h)).json()},
        "tickets": {t["id"] for t in (await client.get(f"{B}/support", headers=h)).json()},
        "saas": {i["id"] for i in (await client.get(f"{B}/saas-invoices", headers=h)).json()},
    }
    assert a["order"]["id"] not in own_ids["orders"] and b["order"]["id"] in own_ids["orders"]
    assert a["item"]["id"] not in own_ids["items"]
    assert a["supplier"]["id"] not in own_ids["suppliers"]
    assert len(own_ids["tickets"]) == 1
