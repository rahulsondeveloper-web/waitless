"""Phase 8: serving timers & automatic discounts (PRD §14).

Acceptance (test 11): a paid pre-order's timer starts at Confirm Arrival, not when it was ordered.
The clock is moved by patching the services' `_now` (the database trigger forbids rewriting a start).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker, use_system
from app.integrations.payments.gateway import MockGateway
from app.services import orders as orders_svc
from app.services import reservations as res_svc
from app.services import sla as sla_svc
from tests.integration.test_bookings import _book, _otp_login, _setup, _tomorrow_at
from tests.integration.test_orders import _dish, _join, _seat, _staff

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"


def _clock(monkeypatch: pytest.MonkeyPatch, at: datetime) -> None:
    for mod in (orders_svc, sla_svc, res_svc):
        monkeypatch.setattr(mod, "_now", lambda at=at: at)


async def _status(client: httpx.AsyncClient, h: dict, order_id: str, to: str) -> dict:
    r = await client.post(f"{B}/orders/{order_id}/status", json={"status": to}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def _tick(at: datetime) -> list:
    async with get_sessionmaker()() as session:
        return await sla_svc.tick(session, now=at)


def _iso(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


async def test_walk_in_timer_starts_on_accept_and_discount_freezes_when_served(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, h, branch, tables = await _setup(client)
    dish = await _dish(client, h, "Dal Makhani", "500", tax_pct="5")
    t = await _join(client, tenant["slug"], await _seat(client, h, tables["T1"]))
    placed = await client.post(
        "/api/v1/table-session/orders", json={"items": [{"menu_item_id": dish["id"], "quantity": 2}]}, headers=t
    )
    o = placed.json()
    assert o["sla"] is None and o["payable_total"] == "1050.00"  # no timer before the kitchen accepts

    accepted = await _status(client, h, o["id"], "accepted")
    start = _iso(accepted["sla"]["started_at"])
    assert start == _iso(accepted["accepted_at"]) and accepted["sla"]["start_reason"] == "accepted"
    assert _iso(accepted["sla"]["deadline_at"]) - start == timedelta(minutes=15)
    assert accepted["sla"]["discount_pct"] == "0.00" and accepted["sla"]["eligible"] is True

    # 21 minutes later: 4 % off the food (40), tax on 960 → 48, payable 1008
    later = start + timedelta(minutes=21)
    _clock(monkeypatch, later)
    view = (await client.get("/api/v1/table-session", headers=t)).json()
    assert view["orders"][0]["sla"]["discount_pct"] == "4.00"
    assert view["discount_total"] == "40.00" and view["payable_total"] == "1008.00"
    assert view["promise"]["serving_minutes"] == 15 and view["promise"]["max_pct"] == "20.00"

    changed = await _tick(later)
    assert [c.id for c in changed] == [uuid.UUID(o["id"])]
    async with get_sessionmaker()() as session:
        await use_system(session)
        row = (
            await session.execute(
                text("select pct, amount from order_discounts where order_id = :i and kind = 'sla_delay'"),
                {"i": o["id"]},
            )
        ).one()
        nb = (
            await session.execute(text("select next_boundary_at from order_sla where order_id = :i"), {"i": o["id"]})
        ).scalar_one()
    assert tuple(row) == (Decimal("4.00"), Decimal("40.00")) and nb == start + timedelta(minutes=25)
    assert await _tick(later) == []  # nothing more until 25:00

    await _status(client, h, o["id"], "preparing")
    await _status(client, h, o["id"], "ready")
    served = await _status(client, h, o["id"], "served")
    assert served["sla"]["status"] == "served" and served["sla"]["discount_pct"] == "4.00"

    _clock(monkeypatch, start + timedelta(hours=2))  # frozen: waiting longer after serving changes nothing
    again = (await client.get("/api/v1/table-session", headers=t)).json()["orders"][0]
    assert again["sla"]["discount_pct"] == "4.00" and again["payable_total"] == "1008.00"
    assert await _tick(start + timedelta(hours=2)) == []


async def test_paid_preorder_timer_starts_at_arrival_not_at_order_time(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, h, branch, _ = await _setup(client)
    slug = tenant["slug"]
    dish = await _dish(client, h, "Garlic Bread", "180")
    policy = (await client.get(f"{B}/branches/{branch['id']}/booking-policy", headers=h)).json()
    await client.put(
        f"{B}/branches/{branch['id']}/booking-policy",
        json={**policy, "paid_enabled": True, "booking_fee": "300"},
        headers=h,
    )
    guest = await _otp_login(client)
    booked = (await _book(client, slug, guest, branch, _tomorrow_at(19), type="paid")).json()
    res = booked["reservation"]
    raw, sig = MockGateway.build_event(booked["payment"]["order_id"], Decimal("300"), True)
    await client.post("/api/v1/webhooks/payments/mock", content=raw, headers={"X-Mock-Signature": sig})
    pre = (
        await client.post(
            f"/api/v1/me/reservations/{res['id']}/orders",
            json={"items": [{"menu_item_id": dish["id"], "quantity": 2}]},
            headers=guest,
        )
    ).json()
    assert pre["order_type"] == "paid_preorder" and pre["sla"] is None
    ordered_at = _iso(pre["placed_at"])

    # The guests arrive 3 hours after pre-ordering: the timer starts then, at the server's arrival time.
    arrival = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=3)
    _clock(monkeypatch, arrival)
    assert (await client.post(f"{B}/reservations/{res['id']}/arrive", json={}, headers=h)).status_code == 200
    mine = (await client.get(f"/api/v1/me/reservations/{res['id']}/orders", headers=guest)).json()[0]
    assert mine["sla"]["start_reason"] == "arrival_confirmed"
    assert _iso(mine["sla"]["started_at"]) == arrival and arrival - ordered_at > timedelta(hours=2)
    assert mine["sla"]["discount_pct"] == "0.00"  # 3 h after ordering, but 0 min after arrival

    _clock(monkeypatch, arrival + timedelta(minutes=5))
    accepted = await _status(client, h, pre["id"], "accepted")  # accepting later does not restart it
    assert _iso(accepted["sla"]["started_at"]) == arrival
    _clock(monkeypatch, arrival + timedelta(minutes=16))
    later = (await client.get(f"/api/v1/me/reservations/{res['id']}/orders", headers=guest)).json()[0]
    assert later["sla"]["discount_pct"] == "2.00"


async def test_policy_screen_snapshot_eligibility_and_cancel(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, h, branch, tables = await _setup(client)
    dish = await _dish(client, h, "Paneer Roll", "200", tax_pct="0")
    got = (await client.get(f"{B}/discount-policy", headers=h)).json()
    assert got["is_default"] is True and got["serving_minutes"] == 15 and got["max_pct"] == "20.00"
    assert set(got["eligible_order_types"]) == {"walk_in", "booking", "staff", "paid_preorder"}
    body = {k: v for k, v in got.items() if k not in ("is_default", "updated_at")}

    waiter = await _staff(client, h, branch, "waiter")
    assert (await client.get(f"{B}/discount-policy", headers=waiter)).status_code == 403
    bad = await client.put(f"{B}/discount-policy", json={**body, "initial_pct": "10", "max_pct": "5"}, headers=h)
    assert bad.status_code == 422

    # An order whose timer started under the default policy …
    seated = await _seat(client, h, tables["T1"])
    t = await _join(client, tenant["slug"], seated)
    line = {"items": [{"menu_item_id": dish["id"], "quantity": 1}]}
    first = (await client.post("/api/v1/table-session/orders", json=line, headers=t)).json()
    start = _iso((await _status(client, h, first["id"], "accepted"))["sla"]["started_at"])

    # … keeps it after the owner changes the policy (10 min, 5 % then +5 % per 5 min, cap 10, no staff orders).
    new = {
        **body,
        "serving_minutes": 10,
        "initial_pct": "5",
        "increment_pct": "5",
        "max_pct": "10",
        "eligible_order_types": ["walk_in", "booking", "paid_preorder"],
    }
    saved = await client.put(f"{B}/discount-policy", json=new, headers=h)
    assert saved.status_code == 200 and saved.json()["is_default"] is False
    staff_order = await client.post(
        f"{B}/orders", json={"table_session_id": seated["session"]["id"], **line}, headers=h
    )
    s_id = staff_order.json()["id"]
    second = (await client.post("/api/v1/table-session/orders", json=line, headers=t)).json()
    await _status(client, h, s_id, "accepted")
    await _status(client, h, second["id"], "accepted")

    _clock(monkeypatch, start + timedelta(minutes=12))
    listed = (await client.get(f"{B}/orders", params={"branch_id": branch["id"]}, headers=h)).json()
    orders = {o["id"]: o for o in listed}
    assert orders[first["id"]]["sla"]["discount_pct"] == "0.00"  # old snapshot: 15 min
    assert orders[first["id"]]["sla"]["serving_minutes"] == 15
    assert orders[second["id"]]["sla"]["discount_pct"] == "5.00"  # new policy: > 10 min
    assert orders[s_id]["sla"]["eligible"] is False and orders[s_id]["sla"]["discount_pct"] == "0.00"
    view = (await client.get("/api/v1/table-session", headers=t)).json()
    assert view["promise"]["serving_minutes"] == 10

    # Cancelling stops the timer — no discount on a cancelled order.
    cancelled = await client.post(f"{B}/orders/{second['id']}/cancel", json={"reason": "Out of paneer"}, headers=h)
    assert cancelled.json()["sla"]["status"] == "cancelled" and cancelled.json()["discount_total"] == "0.00"

    # The timer start and the policy copy cannot be rewritten, even directly in the database.
    async with get_sessionmaker()() as session:
        await use_system(session)
        with pytest.raises(DBAPIError):
            await session.execute(
                text("update order_sla set sla_started_at = sla_started_at - interval '1 hour' where order_id = :i"),
                {"i": first["id"]},
            )

    # Each restaurant has its own policy.
    _, other_h, _, _ = await _setup(client, name="Other Diner")
    assert (await client.get(f"{B}/discount-policy", headers=other_h)).json()["is_default"] is True
