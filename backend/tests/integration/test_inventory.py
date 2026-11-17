"""Phase 9: inventory, suppliers, purchases, transfers, recipes, order consumption, alerts and reports.

Acceptance (test 13): accepting an order deducts exact recipe quantities once; cancelling reverses;
retrying accept does not double-deduct.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker, use_system, use_tenant
from app.models.orders import Order
from app.services import inventory as inv
from tests.integration.test_bookings import _setup
from tests.integration.test_operations import _second_branch
from tests.integration.test_orders import _dish, _join, _seat, _staff

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
INV = f"{B}/inventory"


async def _item(client: httpx.AsyncClient, h: dict, name: str, unit: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    r = await client.post(f"{INV}/items", json={"name": name, "unit": unit, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _move(
    client: httpx.AsyncClient, h: dict, branch: dict, item: dict, type: str, qty: str, reason: str = "", **kw
):  # type: ignore[no-untyped-def]
    return await client.post(
        f"{INV}/movements",
        json={"branch_id": branch["id"], "item_id": item["id"], "type": type, "quantity": qty, "reason": reason, **kw},
        headers=h,
    )


async def _on_hand(client: httpx.AsyncClient, h: dict, branch: dict) -> dict[str, Decimal]:
    rows = (await client.get(f"{INV}/stock", params={"branch_id": branch["id"]}, headers=h)).json()
    return {r["name"]: Decimal(r["on_hand"]) for r in rows}


async def test_items_and_manual_movements_always_have_a_reason(client: httpx.AsyncClient) -> None:
    _, h, branch, _ = await _setup(client)
    sup = await client.post(f"{B}/suppliers", json={"name": "Fresh Dairy Co", "phone": "+919800000001"}, headers=h)
    assert sup.status_code == 201
    cat = (await client.post(f"{INV}/categories", json={"name": "Dairy"}, headers=h)).json()
    paneer = await _item(
        client,
        h,
        "Paneer",
        "kg",
        sku="dai-001",
        category_id=cat["id"],
        supplier_id=sup.json()["id"],
        reorder_level="2",
        min_stock="1",
        purchase_price="320",
    )
    assert (
        paneer["sku"] == "DAI-001"
        and paneer["category_name"] == "Dairy"
        and paneer["supplier_name"] == "Fresh Dairy Co"
    )
    dup = await client.post(f"{INV}/items", json={"name": "paneer", "unit": "kg"}, headers=h)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_NAME"

    assert (await _move(client, h, branch, paneer, "opening", "5")).status_code == 201
    again = await _move(client, h, branch, paneer, "opening", "5")
    assert again.status_code == 409 and again.json()["error"]["code"] == "OPENING_EXISTS"
    no_reason = await _move(client, h, branch, paneer, "wastage", "0.5")
    assert no_reason.status_code == 422  # never modify stock silently
    waste = await _move(client, h, branch, paneer, "wastage", "0.5", "Spoiled overnight")
    assert waste.json()["quantity"] == "-0.500" and waste.json()["balance_after"] == "4.500"
    assert waste.json()["actor_name"]
    too_much = await _move(client, h, branch, paneer, "damage", "10", "Dropped")
    assert too_much.status_code == 409 and too_much.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    count = await _move(client, h, branch, paneer, "adjustment", "4.2", "Weekly count")
    assert count.json()["quantity"] == "-0.300" and count.json()["reason"].startswith("Count 4.2 kg")

    unit_change = await client.put(f"{INV}/items/{paneer['id']}", json={**paneer, "unit": "g"}, headers=h)
    assert unit_change.status_code == 409 and unit_change.json()["error"]["code"] == "UNIT_LOCKED"

    ledger = (await client.get(f"{INV}/movements", params={"branch_id": branch["id"]}, headers=h)).json()
    assert [m["type"] for m in ledger] == ["adjustment", "wastage", "opening"]
    stock = (await client.get(f"{INV}/stock", params={"branch_id": branch["id"]}, headers=h)).json()[0]
    assert stock["on_hand"] == "4.200" and stock["state"] == "ok" and stock["value"] == "1344.00"

    # The ledger is insert-only, even for the database owner of the app.
    async with get_sessionmaker()() as session:
        await use_system(session)
        with pytest.raises(DBAPIError):
            await session.execute(
                text("update inventory_movements set quantity = 100 where id = :i"), {"i": waste.json()["id"]}
            )


async def test_accept_deducts_recipe_once_and_cancel_reverses(client: httpx.AsyncClient) -> None:
    """Acceptance test 13."""
    tenant, h, branch, tables = await _setup(client)
    paneer = await _item(client, h, "Paneer", "kg", purchase_price="300")
    butter = await _item(client, h, "Butter", "kg", purchase_price="500")
    cream = await _item(client, h, "Cream", "l", purchase_price="200")
    for it, q in ((paneer, "5"), (butter, "1"), (cream, "2")):
        await _move(client, h, branch, it, "opening", q)
    dish = await _dish(client, h, "Paneer Butter Masala", "320")
    opts = await client.put(
        f"{B}/menu/items/{dish['id']}/options",
        json={"variants": [{"name": "Half", "price": "200"}, {"name": "Full", "price": "320"}]},
        headers=h,
    )
    half, full = opts.json()["variants"]
    recipe = await client.put(
        f"{B}/menu/items/{dish['id']}/recipe",
        json={
            "lines": [
                {"inventory_item_id": paneer["id"], "quantity": "150", "unit": "g"},
                {"inventory_item_id": butter["id"], "quantity": "20", "unit": "g"},
                {"inventory_item_id": cream["id"], "quantity": "30", "unit": "ml"},
                # The half portion uses its own, smaller recipe.
                {"inventory_item_id": paneer["id"], "variant_id": half["id"], "quantity": "80", "unit": "g"},
            ]
        },
        headers=h,
    )
    assert recipe.status_code == 200, recipe.text
    assert recipe.json()["cost"] == "61.00"  # 0.15×300 + 0.02×500 + 0.03×200
    bad = await client.put(
        f"{B}/menu/items/{dish['id']}/recipe",
        json={"lines": [{"inventory_item_id": paneer["id"], "quantity": "1", "unit": "ml"}]},
        headers=h,
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "UNIT_MISMATCH"

    t = await _join(client, tenant["slug"], await _seat(client, h, tables["T1"]))
    o = (
        await client.post(
            "/api/v1/table-session/orders",
            json={
                "items": [
                    {"menu_item_id": dish["id"], "variant_id": full["id"], "quantity": 2},
                    {"menu_item_id": dish["id"], "variant_id": half["id"], "quantity": 1},
                ]
            },
            headers=t,
        )
    ).json()
    assert await _on_hand(client, h, branch) == {"Butter": Decimal("1"), "Cream": Decimal("2"), "Paneer": Decimal("5")}

    assert (
        await client.post(f"{B}/orders/{o['id']}/status", json={"status": "accepted"}, headers=h)
    ).status_code == 200
    # Full ×2: paneer 0.300, butter 0.040, cream 0.060 · Half ×1: paneer 0.080 only
    after = {"Butter": Decimal("0.960"), "Cream": Decimal("1.940"), "Paneer": Decimal("4.620")}
    assert await _on_hand(client, h, branch) == after

    retry = await client.post(f"{B}/orders/{o['id']}/status", json={"status": "accepted"}, headers=h)
    assert retry.status_code == 409  # already accepted
    async with get_sessionmaker()() as session:  # even calling the deduction again writes nothing
        await use_system(session)
        order = await session.get(Order, uuid.UUID(o["id"]))
        assert order is not None
        await use_tenant(session, order.tenant_id)
        assert await inv.consume_order(session, order, None) == 0
        await session.commit()
    assert await _on_hand(client, h, branch) == after
    used = (
        await client.get(f"{INV}/movements", params={"branch_id": branch["id"], "type": "consumption"}, headers=h)
    ).json()
    assert len(used) == 4 and all(m["order_number"] == o["number"] for m in used)

    cancel = await client.post(f"{B}/orders/{o['id']}/cancel", json={"reason": "Guest left"}, headers=h)
    assert cancel.status_code == 200
    assert await _on_hand(client, h, branch) == {"Butter": Decimal("1"), "Cream": Decimal("2"), "Paneer": Decimal("5")}
    async with get_sessionmaker()() as session:
        await use_system(session)
        order = await session.get(Order, uuid.UUID(o["id"]))
        assert order is not None
        await use_tenant(session, order.tenant_id)
        assert await inv.reverse_order(session, order, None) == 0  # a second reversal is impossible
        await session.commit()

    # A cancel before the kitchen accepted never touched stock.
    o2 = (
        await client.post(
            "/api/v1/table-session/orders",
            json={"items": [{"menu_item_id": dish["id"], "variant_id": full["id"]}]},
            headers=t,
        )
    ).json()
    await client.post(f"{B}/orders/{o2['id']}/cancel", json={"reason": "Changed mind"}, headers=h)
    assert await _on_hand(client, h, branch) == {"Butter": Decimal("1"), "Cream": Decimal("2"), "Paneer": Decimal("5")}

    report = (await client.get(f"{INV}/reports/consumption", params={"branch_id": branch["id"]}, headers=h)).json()
    assert all(r[2] == 0 for r in report["rows"])  # used then put back


async def test_purchase_receive_pay_and_supplier_history(client: httpx.AsyncClient) -> None:
    _, h, branch, _ = await _setup(client)
    sup = (await client.post(f"{B}/suppliers", json={"name": "Veg Mandi"}, headers=h)).json()
    tomato = await _item(client, h, "Tomato", "kg", purchase_price="30", reorder_level="5")
    milk = await _item(client, h, "Milk", "l", purchase_price="50", tracks_expiry=True)
    await _move(client, h, branch, tomato, "opening", "10", unit_cost="30")

    po = await client.post(
        f"{B}/purchases",
        json={
            "branch_id": branch["id"],
            "supplier_id": sup["id"],
            "items": [
                {"item_id": tomato["id"], "quantity": "10", "unit_price": "40", "tax_pct": "5"},
                {"item_id": milk["id"], "quantity": "20", "unit_price": "55"},
            ],
        },
        headers=h,
    )
    assert po.status_code == 201, po.text
    p = po.json()
    assert p["number"].startswith("PO-") and p["status"] == "draft"
    assert (p["subtotal"], p["tax_total"], p["grand_total"]) == ("1500.00", "20.00", "1520.00")
    assert (await client.post(f"{B}/purchases/{p['id']}/order", headers=h)).json()["status"] == "ordered"

    no_expiry = await client.post(f"{B}/purchases/{p['id']}/receive", json={}, headers=h)
    assert no_expiry.status_code == 422 and no_expiry.json()["error"]["code"] == "EXPIRY_REQUIRED"
    soon = (date.today() + timedelta(days=3)).isoformat()
    got = await client.post(
        f"{B}/purchases/{p['id']}/receive",
        json={
            "invoice_number": "INV-77",
            "items": [
                {"item_id": tomato["id"], "received_quantity": "8"},  # 2 kg short
                {"item_id": milk["id"], "received_quantity": "20", "expiry_date": soon},
            ],
        },
        headers=h,
    )
    assert got.status_code == 200, got.text
    r = got.json()
    assert r["status"] == "received" and r["invoice_number"] == "INV-77"
    assert r["grand_total"] == "1436.00"  # 8×40 + 5 % + 20×55
    stock = {
        s["name"]: s for s in (await client.get(f"{INV}/stock", params={"branch_id": branch["id"]}, headers=h)).json()
    }
    assert stock["Tomato"]["on_hand"] == "18.000"
    assert stock["Tomato"]["avg_cost"] == "34.44"  # (10×30 + 8×40) / 18
    items = {i["name"]: i for i in (await client.get(f"{INV}/items", headers=h)).json()}
    assert items["Tomato"]["purchase_price"] == "40.00" and items["Milk"]["supplier_name"] == "Veg Mandi"
    assert (await client.post(f"{B}/purchases/{p['id']}/receive", json={}, headers=h)).status_code == 409

    pay = await client.post(f"{B}/purchases/{p['id']}/payments", json={"amount": "1000", "method": "upi"}, headers=h)
    assert pay.json()["payment_status"] == "partial"
    over = await client.post(f"{B}/purchases/{p['id']}/payments", json={"amount": "1000", "method": "cash"}, headers=h)
    assert over.status_code == 409 and over.json()["error"]["code"] == "OVERPAYMENT"
    suppliers = {s["name"]: s for s in (await client.get(f"{B}/suppliers", headers=h)).json()}
    assert suppliers["Veg Mandi"]["purchases_total"] == "1436.00" and suppliers["Veg Mandi"]["outstanding"] == "436.00"
    done = await client.post(f"{B}/purchases/{p['id']}/payments", json={"amount": "436", "method": "bank"}, headers=h)
    assert done.json()["payment_status"] == "paid" and len(done.json()["payments"]) == 2

    alerts = (await client.get(f"{INV}/alerts", params={"branch_id": branch["id"]}, headers=h)).json()
    assert [e["name"] for e in alerts["expiring"]] == ["Milk"] and alerts["expiring"][0]["days_left"] == 3

    history = (await client.get(f"{INV}/reports/purchases", params={"branch_id": branch["id"]}, headers=h)).json()
    assert history["rows"][0][0] == p["number"] and history["totals"]["Outstanding"] == "0.00"


async def test_transfers_between_branches_are_controlled(client: httpx.AsyncClient) -> None:
    _, h, main, _ = await _setup(client)
    other = await _second_branch(client, h, "Koregaon Park")
    rice = await _item(client, h, "Basmati Rice", "kg", purchase_price="90")
    await _move(client, h, main, rice, "opening", "50")

    too_much = await client.post(
        f"{INV}/transfers",
        json={
            "from_branch_id": main["id"],
            "to_branch_id": other["id"],
            "items": [{"item_id": rice["id"], "quantity": "80"}],
        },
        headers=h,
    )
    assert too_much.status_code == 409 and too_much.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    sent = await client.post(
        f"{INV}/transfers",
        json={
            "from_branch_id": main["id"],
            "to_branch_id": other["id"],
            "items": [{"item_id": rice["id"], "quantity": "20"}],
        },
        headers=h,
    )
    assert sent.status_code == 201 and sent.json()["status"] == "in_transit"
    tr = sent.json()
    assert (await _on_hand(client, h, main))["Basmati Rice"] == Decimal("30")
    assert (await _on_hand(client, h, other))["Basmati Rice"] == Decimal("0")  # not until received

    received = await client.post(f"{INV}/transfers/{tr['id']}/receive", headers=h)
    assert received.json()["status"] == "received"
    assert (await _on_hand(client, h, other))["Basmati Rice"] == Decimal("20")
    assert (await client.post(f"{INV}/transfers/{tr['id']}/cancel", headers=h)).status_code == 409

    second = (
        await client.post(
            f"{INV}/transfers",
            json={
                "from_branch_id": main["id"],
                "to_branch_id": other["id"],
                "items": [{"item_id": rice["id"], "quantity": "5"}],
            },
            headers=h,
        )
    ).json()
    await client.post(f"{INV}/transfers/{second['id']}/cancel", headers=h)
    assert (await _on_hand(client, h, main))["Basmati Rice"] == Decimal("30")
    listed = (await client.get(f"{INV}/transfers", params={"branch_id": other["id"]}, headers=h)).json()
    assert {t["status"] for t in listed} == {"received", "cancelled"}


async def test_alerts_reports_permissions_and_isolation(client: httpx.AsyncClient) -> None:
    _, h, branch, _ = await _setup(client)
    oil = await _item(client, h, "Oil", "l", reorder_level="5", min_stock="2", purchase_price="150")
    salt = await _item(client, h, "Salt", "pkt", purchase_price="20")
    await _move(client, h, branch, oil, "opening", "6")
    await _move(client, h, branch, oil, "wastage", "2", "Spilled")
    await _move(client, h, branch, salt, "opening", "1")
    await _move(client, h, branch, salt, "damage", "1", "Wet")

    alerts = (await client.get(f"{INV}/alerts", params={"branch_id": branch["id"]}, headers=h)).json()
    assert [a["name"] for a in alerts["low"]] == ["Oil"] and alerts["low"][0]["suggested_quantity"] == "6.000"
    assert [a["name"] for a in alerts["out"]] == ["Salt"]

    for kind in ("current", "valuation", "movements", "consumption", "wastage", "purchases", "low_stock", "expiry"):
        r = await client.get(f"{INV}/reports/{kind}", params={"branch_id": branch["id"]}, headers=h)
        assert r.status_code == 200, (kind, r.text)
    wastage = (await client.get(f"{INV}/reports/wastage", params={"branch_id": branch["id"]}, headers=h)).json()
    assert wastage["totals"]["Value"] == "320.00" and len(wastage["rows"]) == 2  # 2 l oil × 150 + 1 pkt × 20
    valuation = (await client.get(f"{INV}/reports/valuation", params={"branch_id": branch["id"]}, headers=h)).json()
    assert valuation["totals"]["Value"] == "600.00"

    kitchen = await _staff(client, h, branch, "kitchen")
    assert (await client.get(f"{INV}/stock", params={"branch_id": branch["id"]}, headers=kitchen)).status_code == 200
    assert (await _move(client, kitchen, branch, oil, "wastage", "1", "x")).status_code == 403
    waiter = await _staff(client, h, branch, "waiter")
    assert (await client.get(f"{INV}/stock", params={"branch_id": branch["id"]}, headers=waiter)).status_code == 403
    assert (await client.get(f"{B}/purchases", headers=waiter)).status_code == 403

    _, other_h, other_branch, _ = await _setup(client, name="Rival Kitchen")
    assert (await client.get(f"{INV}/items", headers=other_h)).json() == []
    assert (await client.put(f"{INV}/items/{oil['id']}", json={**oil}, headers=other_h)).status_code == 404
    cross = await _move(client, other_h, branch, oil, "addition", "1", "sneaky")
    assert cross.status_code == 404  # the other restaurant's branch does not exist for them
