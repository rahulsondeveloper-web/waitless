"""Phase 10: bills from table sessions, discounts within limits, payments, invoices, refunds, Finish → pay online,
booking credit, split & merge, closing a table only when paid."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker, use_system
from app.integrations.payments.gateway import MockGateway
from tests.integration.test_bookings import _book, _otp_login, _setup, _tomorrow_at
from tests.integration.test_orders import _dish, _join, _seat, _staff

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
T = "/api/v1/table-session"


async def _settings(client: httpx.AsyncClient, h: dict, **kw) -> dict:  # type: ignore[no-untyped-def]
    cur = (await client.get(f"{B}/billing-settings", headers=h)).json()
    r = await client.put(f"{B}/billing-settings", json={**cur, **kw}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def _order(client: httpx.AsyncClient, t: dict, *lines: tuple[dict, int]) -> dict:
    r = await client.post(
        f"{T}/orders", json={"items": [{"menu_item_id": d["id"], "quantity": q} for d, q in lines]}, headers=t
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _serve(client: httpx.AsyncClient, h: dict, order: dict) -> None:
    for st in ("accepted", "preparing", "ready", "served"):
        r = await client.post(f"{B}/orders/{order['id']}/status", json={"status": st}, headers=h)
        assert r.status_code == 200, r.text


async def test_bill_discount_limits_payments_invoice_and_close(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    await _settings(
        client, h, service_charge_pct="5", service_charge_tax_pct="5", round_off=True, gstin="27ABCDE1234F1Z5"
    )
    paneer = await _dish(client, h, "Paneer Tikka", "249", tax_pct="5")
    soda = await _dish(client, h, "Lime Soda", "89", tax_pct="12")
    seated = await _seat(client, h, tables["T1"])
    sid = seated["session"]["id"]
    t = await _join(client, tenant["slug"], seated)
    o1 = await _order(client, t, (paneer, 2), (soda, 2))
    await _serve(client, h, o1)

    # Guests cannot leave with an unpaid bill.
    early = await client.post(f"{B}/table-sessions/{sid}/close", headers=h)
    assert early.status_code == 409 and early.json()["error"]["code"] == "BILL_UNPAID"

    bills = (await client.post(f"{B}/table-sessions/{sid}/bill", headers=h)).json()
    assert len(bills["bills"]) == 1
    bill = bills["bills"][0]
    # Food 498 + 178 = 676 · service 5 % = 33.80 · GST 5 % on (498 + 33.80) = 26.59 · 12 % on 178 = 21.36
    # = 757.75 → round off +0.25 → 758.00
    assert (bill["subtotal"], bill["service_charge"], bill["tax_total"], bill["grand_total"]) == (
        "676.00",
        "33.80",
        "47.95",
        "758.00",
    )
    assert bill["round_off"] == "0.25" and bill["label"] == "Bill" and bill["unserved_orders"] == 0

    manager = await _staff(client, h, branch, "manager")
    over = await client.post(
        f"{B}/bills/{bill['id']}/discount", json={"pct": "15", "reason": "Regular"}, headers=manager
    )
    assert over.status_code == 403 and over.json()["error"]["code"] == "DISCOUNT_LIMIT"
    no_reason = await client.post(f"{B}/bills/{bill['id']}/discount", json={"pct": "5"}, headers=manager)
    assert no_reason.status_code == 422
    ok = await client.post(
        f"{B}/bills/{bill['id']}/discount", json={"pct": "10", "reason": "Regular guest"}, headers=manager
    )
    assert ok.status_code == 200 and ok.json()["manual_discount"] == "67.60"
    owner = await client.post(
        f"{B}/bills/{bill['id']}/discount", json={"amount": "100", "reason": "Birthday"}, headers=h
    )
    assert owner.json()["manual_discount"] == "100.00"
    bill = owner.json()
    total = Decimal(bill["grand_total"])

    cashier = await _staff(client, h, branch, "cashier")
    assert (
        await client.post(f"{B}/bills/{bill['id']}/discount", json={"pct": "1", "reason": "x"}, headers=cashier)
    ).status_code == 403
    waiter = await _staff(client, h, branch, "waiter")
    assert (await client.post(f"{B}/table-sessions/{sid}/bill", headers=waiter)).status_code == 403

    key = {"Idempotency-Key": "pay-1"}
    cash = await client.post(
        f"{B}/bills/{bill['id']}/payments",
        json={"method": "cash", "amount": "500", "tendered": "1000"},
        headers={**cashier, **key},
    )
    assert cash.status_code == 201, cash.text
    again = await client.post(
        f"{B}/bills/{bill['id']}/payments",
        json={"method": "cash", "amount": "500", "tendered": "1000"},
        headers={**cashier, **key},
    )
    assert len(again.json()["payments"]) == 1  # same key → one payment
    paid1 = cash.json()
    assert paid1["locked"] is True and paid1["payments"][0]["change_due"] == "500.00"
    assert paid1["due"] == str(total - 500)
    # Locked: no more discounts.
    locked = await client.post(f"{B}/bills/{bill['id']}/discount", json={"pct": "1", "reason": "x"}, headers=h)
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "BILL_LOCKED"
    too_much = await client.post(
        f"{B}/bills/{bill['id']}/payments", json={"method": "card", "amount": "9999"}, headers=cashier
    )
    assert too_much.status_code == 409 and too_much.json()["error"]["code"] == "OVERPAYMENT"
    card = await client.post(
        f"{B}/bills/{bill['id']}/payments",
        json={"method": "card", "amount": str(total - 500), "reference": "VISA 4242"},
        headers=cashier,
    )
    done = card.json()
    assert done["status"] == "paid" and done["due"] == "0.00"
    inv = done["invoices"][0]
    assert inv["kind"] == "invoice" and inv["number"] == "INV-000001" and inv["total"] == str(total)

    pdf = await client.get(f"{B}/invoices/{inv['id']}/pdf", headers=cashier)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    receipt = await client.get(f"{B}/invoices/{inv['id']}/pdf?format=receipt", headers=cashier)
    assert receipt.content[:5] == b"%PDF-"
    snap = (await client.get(f"{B}/invoices/{inv['id']}", headers=h)).json()["snapshot"]
    assert snap["restaurant"]["gstin"] == "27ABCDE1234F1Z5" and snap["bill"]["grand_total"] == str(total)

    async with get_sessionmaker()() as session:  # issued invoices never change
        await use_system(session)
        with pytest.raises(DBAPIError):
            await session.execute(text("update invoices set total = 1 where id = :i"), {"i": inv["id"]})

    # Refunds: manager limit, then the owner; each one is a credit note.
    pay_card = next(p for p in done["payments"] if p["method"] == "card")
    big = await client.post(
        f"{B}/payments/{pay_card['id']}/refunds", json={"amount": "50", "reason": "Cold food"}, headers=cashier
    )
    assert big.status_code == 403  # cashiers cannot refund
    refunded = await client.post(
        f"{B}/payments/{pay_card['id']}/refunds",
        json={"amount": "50", "reason": "Cold food"},
        headers={**manager, "Idempotency-Key": "r1"},
    )
    assert refunded.status_code == 201
    same = await client.post(
        f"{B}/payments/{pay_card['id']}/refunds",
        json={"amount": "50", "reason": "Cold food"},
        headers={**manager, "Idempotency-Key": "r1"},
    )
    assert same.json()["refunded_total"] == "50.00"
    notes = [i for i in same.json()["invoices"] if i["kind"] == "credit_note"]
    assert len(notes) == 1 and notes[0]["number"] == "CN-000001" and notes[0]["total"] == "-50.00"
    over_refund = await client.post(
        f"{B}/payments/{pay_card['id']}/refunds", json={"amount": "99999", "reason": "x"}, headers=h
    )
    assert over_refund.status_code == 409

    closed = await client.post(f"{B}/table-sessions/{sid}/close", headers=h)
    assert closed.status_code == 200, closed.text
    history = (await client.get(f"{B}/payments", params={"branch_id": branch["id"]}, headers=cashier)).json()
    assert {p["method"] for p in history} == {"cash", "card"} and history[0]["invoice_number"] == "INV-000001"


async def test_guest_finish_pays_online_and_gets_the_receipt(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    await _settings(client, h, round_off=False)
    dish = await _dish(client, h, "Masala Dosa", "150", tax_pct="5")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    o = await _order(client, t, (dish, 2))
    await _serve(client, h, o)

    fin = await client.post(f"{T}/finish", headers=t)
    assert fin.status_code == 200 and fin.json()["session_status"] == "finished"
    bill = fin.json()["bills"][0]
    assert bill["grand_total"] == "315.00"
    blocked = await client.post(f"{T}/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers=t)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "SESSION_CLOSED"

    # Staff can reopen a finished (unpaid) table: the guest orders more, then finishes again.
    reopened = await client.post(f"{B}/table-sessions/{seated['session']['id']}/reopen", headers=h)
    assert reopened.json()["session_status"] == "open"
    await _serve(client, h, await _order(client, t, (dish, 1)))
    fin = await client.post(f"{T}/finish", headers=t)
    bill = fin.json()["bills"][0]
    assert bill["grand_total"] == "472.50"

    pay = await client.post(f"{T}/bills/{bill['id']}/pay", headers=t)
    assert pay.status_code == 200, pay.text
    order_id = pay.json()["order_id"]
    assert pay.json()["amount"] == "472.50"
    raw, sig = MockGateway.build_event(order_id, Decimal("472.50"), True)
    hook = await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    assert hook.json()["result"] == "paid"
    replay = await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    assert replay.json()["result"] == "already_processed"

    after = (await client.get(f"{T}/bills", headers=t)).json()
    paid = after["bills"][0]
    assert paid["status"] == "paid" and paid["payments"][0]["method"] == "gateway"
    # Paid in full with nothing cooking → the visit closed by itself and the table went to cleaning.
    assert after["session_status"] == "closed"
    board = (await client.get(f"{B}/tables", params={"branch_id": seated["session"]["branch_id"]}, headers=h)).json()
    assert next(x for x in board if x["id"] == tables["T1"]["id"])["status"] == "cleaning"
    # The receipt still downloads with the same table link, and later with the order ID + PIN.
    receipt = await client.get(f"{T}/invoices/{paid['invoices'][0]['id']}/pdf?t={t['X-Table-Token']}")
    assert receipt.status_code == 200 and receipt.content[:5] == b"%PDF-"
    assert (await client.get(f"{T}/invoices/{paid['invoices'][0]['id']}/pdf")).status_code == 401
    assert (
        await client.post(f"{T}/orders", json={"items": [{"menu_item_id": dish["id"]}]}, headers=t)
    ).status_code == 409
    # Reopening is for finished tables, not closed ones.
    late = await client.post(f"{B}/table-sessions/{seated['session']['id']}/reopen", headers=h)
    assert late.status_code == 409


async def test_booking_credit_split_merge_and_cancelled_lines(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    slug = tenant["slug"]
    await _settings(client, h, round_off=False)
    policy = (await client.get(f"{B}/branches/{branch['id']}/booking-policy", headers=h)).json()
    await client.put(
        f"{B}/branches/{branch['id']}/booking-policy",
        json={**policy, "paid_enabled": True, "booking_fee": "300"},
        headers=h,
    )
    thali = await _dish(client, h, "Veg Thali", "400", tax_pct="5")
    lassi = await _dish(client, h, "Sweet Lassi", "100", tax_pct="5")

    guest = await _otp_login(client)
    booked = (await _book(client, slug, guest, branch, _tomorrow_at(20), type="paid")).json()
    raw, sig = MockGateway.build_event(booked["payment"]["order_id"], Decimal("300"), True)
    await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    seated = (await client.post(f"{B}/reservations/{booked['reservation']['id']}/arrive", json={}, headers=h)).json()
    t = await _join(client, slug, seated)
    o1 = await _order(client, t, (thali, 1), (lassi, 2))
    o2 = await _order(client, t, (lassi, 1))

    sb = (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=h)).json()
    bill = sb["bills"][0]
    # 400 + 200 + 100 = 700 + 5 % = 735 − booking fee 300 = 435
    assert bill["booking_credit"] == "300.00" and bill["grand_total"] == "435.00"

    # A cancelled order leaves the open bill.
    await client.post(f"{B}/orders/{o2['id']}/cancel", json={"reason": "Changed mind"}, headers=h)
    sb = (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=h)).json()
    assert sb["bills"][0]["grand_total"] == "330.00"  # 600 + 30 − 300

    # Split the lassis to their own bill; the credit stays with one bill only.
    lassi_line = next(ln for ln in sb["bills"][0]["lines"] if ln["name"] == "Sweet Lassi")
    split = await client.post(
        f"{B}/bills/{bill['id']}/split", json={"order_item_ids": [lassi_line["order_item_id"]]}, headers=h
    )
    assert split.status_code == 200, split.text
    b1, b2 = split.json()["bills"]
    assert (b1["label"], b2["label"]) == ("Bill 1", "Bill 2")
    # Bill 1: thali 400 + 5 % − the whole 300 credit = 120 · Bill 2: lassis 200 + 5 % = 210 (no credit left)
    assert (b1["grand_total"], b1["booking_credit"]) == ("120.00", "300.00")
    assert (b2["grand_total"], b2["booking_credit"]) == ("210.00", "0.00")
    everything = await client.post(
        f"{B}/bills/{b1['id']}/split", json={"order_item_ids": [ln["order_item_id"] for ln in b1["lines"]]}, headers=h
    )
    assert everything.status_code == 422

    # Another table's open bill joins this one.
    other = await _seat(client, h, tables["T1"])  # the booking guests sit at T2 (2 seats, their held table)
    t2 = await _join(client, slug, other)
    await _order(client, t2, (lassi, 1))
    other_bill = (await client.post(f"{B}/table-sessions/{other['session']['id']}/bill", headers=h)).json()["bills"][0]
    merged = await client.post(f"{B}/bills/{b1['id']}/merge", json={"source_bill_id": other_bill["id"]}, headers=h)
    assert merged.status_code == 200 and len(merged.json()["lines"]) == 2
    other_view = (await client.post(f"{B}/table-sessions/{other['session']['id']}/bill", headers=h)).json()
    assert other_view["bills"] == [] and other_view["can_close"] is True
    _ = o1


async def test_zero_bill_settles_and_isolation(client: httpx.AsyncClient) -> None:
    tenant, h, _, tables = await _setup(client)
    tea = await _dish(client, h, "Tea", "20", tax_pct="0")
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    await _order(client, t, (tea, 1))
    bill = (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=h)).json()["bills"][0]
    free = await client.post(
        f"{B}/bills/{bill['id']}/discount", json={"pct": "100", "reason": "On the house"}, headers=h
    )
    assert free.json()["grand_total"] == "0.00"
    settled = await client.post(f"{B}/bills/{bill['id']}/settle", headers=h)
    assert settled.json()["status"] == "paid" and settled.json()["invoices"][0]["total"] == "0.00"

    _, other_h, _, _ = await _setup(client, name="Elsewhere Eats")
    assert (await client.get(f"{B}/bills/{bill['id']}", headers=other_h)).status_code == 404
    assert (await client.post(f"{B}/table-sessions/{seated['session']['id']}/bill", headers=other_h)).status_code == 404
