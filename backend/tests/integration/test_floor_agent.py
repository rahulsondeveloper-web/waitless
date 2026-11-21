"""Floor Agent: pairing, and telling only the waiter in charge of the table."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services import floor_agent as svc
from tests.conftest import random_mobile
from tests.integration.test_bookings import _otp_login, _setup
from tests.integration.test_orders import _seat

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"
A = "/api/v1/agent"


def _event(kind: str, table: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    return {
        "event_id": str(kw.pop("event_id", uuid.uuid4())),
        "kind": kind,
        "table": table,
        "at": (kw.pop("at", None) or datetime.now(UTC)).isoformat(),
        "guests": kw.pop("guests", 2),
    }


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict, str]]:
    sent: list[tuple[str, dict, str]] = []

    async def fake_emit(event: str, data: dict, room: str) -> None:
        sent.append((event, data, room))

    monkeypatch.setattr(svc, "emit", fake_emit)
    return sent


async def _waiter(client: httpx.AsyncClient, h: dict, branch: dict, role: str = "waiter") -> tuple[dict, str]:
    """A signed-in staff member of the branch and their user id."""
    roles = {r["key"]: r for r in (await client.get(f"{B}/roles", headers=h)).json()}
    mobile = random_mobile()
    r = await client.post(
        f"{B}/staff",
        json={
            "full_name": f"{role.title()} {mobile[-4:]}",
            "phone": mobile,
            "role_id": roles[role]["id"],
            "branch_ids": [branch["id"]],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return await _otp_login(client, mobile), r.json()["user_id"]


async def _pair(client: httpx.AsyncClient, h: dict, branch: dict) -> dict[str, str]:
    r = await client.post(f"{B}/floor-agents", json={"branch_id": branch["id"], "name": "Front camera"}, headers=h)
    assert r.status_code == 201, r.text
    paired = await client.post(f"{A}/pair", json={"code": r.json()["pairing_code"]})
    assert paired.status_code == 200, paired.text
    return {"X-Agent-Key": paired.json()["agent_key"]}


async def _floor(client: httpx.AsyncClient):  # type: ignore[no-untyped-def]
    """A restaurant with T1 (Rohan), T2 (Priya), T3 (nobody), both waiters and an agent."""
    tenant, h, branch, tables = await _setup(client)
    t3 = await client.post(f"{B}/tables", json={"branch_id": branch["id"], "label": "T3", "capacity": 4}, headers=h)
    tables["T3"] = t3.json()
    (rohan, rid), (priya, pid) = await _waiter(client, h, branch), await _waiter(client, h, branch)
    for label, uid in (("T1", rid), ("T2", pid)):
        r = await client.patch(f"{B}/tables/{tables[label]['id']}", json={"waiter_user_id": uid}, headers=h)
        assert r.status_code == 200, r.text
    agent = await _pair(client, h, branch)
    return tenant, h, branch, tables, (rohan, rid), (priya, pid), agent


async def _mine(client: httpx.AsyncClient, who: dict, branch: dict) -> list[dict]:
    r = await client.get(f"{B}/floor-alerts", params={"branch_id": branch["id"]}, headers=who)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- pairing ----------


async def test_pairing_flow_and_key_rules(client: httpx.AsyncClient) -> None:
    tenant, h, branch, tables = await _setup(client)
    waiter, _ = await _waiter(client, h, branch)

    # Only the owner/manager can add an agent; a waiter cannot.
    denied = await client.post(f"{B}/floor-agents", json={"branch_id": branch["id"]}, headers=waiter)
    assert denied.status_code == 403

    made = (await client.post(f"{B}/floor-agents", json={"branch_id": branch["id"], "name": "Door"}, headers=h)).json()
    code = made["pairing_code"]
    assert len(code) == 9 and code[4] == "-" and made["status"] == "waiting"
    assert (await client.post(f"{A}/pair", json={"code": "WRONG-CODE"})).status_code == 400

    paired = await client.post(f"{A}/pair", json={"code": code.lower().replace("-", " ")})  # typing slack is fine
    assert paired.status_code == 200, paired.text
    key = paired.json()["agent_key"]
    assert key.startswith("wla_") and {t["label"] for t in paired.json()["tables"]} >= {"T1", "T2"}
    again = await client.post(f"{A}/pair", json={"code": code})  # a code works once
    assert again.status_code == 400 and again.json()["error"]["code"] == "PAIRING_CODE_INVALID"

    agent = {"X-Agent-Key": key}
    assert (await client.get(f"{A}/tables", headers=agent)).status_code == 200
    assert (await client.post(f"{A}/heartbeat", headers=agent)).json()["ok"] is True
    assert (await client.get(f"{A}/tables")).status_code == 401  # no key
    assert (await client.get(f"{A}/tables", headers={"X-Agent-Key": "wla_nope"})).status_code == 401

    listed = (await client.get(f"{B}/floor-agents", params={"branch_id": branch["id"]}, headers=h)).json()
    assert [(a["name"], a["status"], a["online"]) for a in listed] == [("Door", "paired", True)]

    # Disconnecting the laptop cuts it off at once.
    assert (await client.delete(f"{B}/floor-agents/{made['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{A}/tables", headers=agent)).status_code == 401


async def test_expired_pairing_code_is_refused(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, h, branch, _ = await _setup(client)
    code = (await client.post(f"{B}/floor-agents", json={"branch_id": branch["id"]}, headers=h)).json()["pairing_code"]
    later = datetime.now(UTC) + timedelta(minutes=16)
    monkeypatch.setattr(svc, "_now", lambda: later)
    assert (await client.post(f"{A}/pair", json={"code": code})).status_code == 400


# ---------- who gets told ----------


async def test_seated_goes_only_to_the_waiter_in_charge(client: httpx.AsyncClient, emitted: list) -> None:
    _, h, branch, tables, (rohan, rid), (priya, pid), agent = await _floor(client)

    ev = _event("seated", "T1")
    r = await client.post(f"{A}/events", json={"events": [ev]}, headers=agent)
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["status"] == "ok" and r.json()["results"][0]["notified"] == rid

    # Live: exactly one push, into Rohan's private room — nothing for Priya, nothing for the whole branch.
    assert [(e, d["table_label"], room) for e, d, room in emitted] == [("floor.alert", "T1", f"u:{rid}")]
    mine = await _mine(client, rohan, branch)
    assert [(a["table_label"], a["kind"], a["user_id"]) for a in mine] == [("T1", "seated_unchecked", rid)]
    assert "not checked in yet" in mine[0]["message"]
    assert await _mine(client, priya, branch) == []

    # The same event sent again (a lost reply) changes nothing.
    again = await client.post(f"{A}/events", json={"events": [ev]}, headers=agent)
    assert again.json()["results"][0]["status"] == "duplicate"
    assert len(emitted) == 1 and len(await _mine(client, rohan, branch)) == 1

    # T2 belongs to Priya.
    await client.post(f"{A}/events", json={"events": [_event("seated", "T2")]}, headers=agent)
    assert emitted[-1][2] == f"u:{pid}" and len(await _mine(client, priya, branch)) == 1
    assert len(await _mine(client, rohan, branch)) == 1

    # Priya cannot clear Rohan's alert; Rohan can.
    rohan_alert = (await _mine(client, rohan, branch))[0]["id"]
    assert (await client.post(f"{B}/floor-alerts/{rohan_alert}/ack", headers=priya)).status_code == 404
    assert (await client.post(f"{B}/floor-alerts/{rohan_alert}/ack", headers=rohan)).status_code == 200
    assert await _mine(client, rohan, branch) == []


async def test_a_table_with_no_waiter_tells_every_waiter(client: httpx.AsyncClient, emitted: list) -> None:
    _, h, branch, tables, (rohan, _), (priya, _), agent = await _floor(client)
    r = await client.post(f"{A}/events", json={"events": [_event("seated", "T3")]}, headers=agent)
    assert r.json()["results"][0]["notified"] == "all_waiters"
    assert emitted[-1][2].endswith(":staff") and emitted[-1][1]["user_id"] is None
    assert len(await _mine(client, rohan, branch)) == 1 and len(await _mine(client, priya, branch)) == 1
    # Whoever clears it clears it for everyone.
    alert_id = (await _mine(client, rohan, branch))[0]["id"]
    await client.post(f"{B}/floor-alerts/{alert_id}/ack", headers=rohan)
    assert await _mine(client, priya, branch) == []


async def test_a_disabled_waiter_is_skipped(client: httpx.AsyncClient, emitted: list) -> None:
    _, h, branch, tables, (rohan, rid), (priya, _), agent = await _floor(client)
    staff = (await client.get(f"{B}/staff", headers=h)).json()
    membership = next(s for s in staff if s["user_id"] == rid)
    await client.patch(f"{B}/staff/{membership['membership_id']}", json={"status": "disabled"}, headers=h)
    r = await client.post(f"{A}/events", json={"events": [_event("seated", "T1")]}, headers=agent)
    assert r.json()["results"][0]["notified"] == "all_waiters"  # T1 had Rohan; he no longer works here
    assert len(await _mine(client, priya, branch)) == 1


async def test_checked_in_table_says_seated_not_unchecked(client: httpx.AsyncClient, emitted: list) -> None:
    _, h, branch, tables, (rohan, _), _, agent = await _floor(client)
    await _seat(client, h, tables["T1"])  # a waiter already opened the table in the app
    await client.post(f"{A}/events", json={"events": [_event("seated", "T1")]}, headers=agent)
    assert (await _mine(client, rohan, branch))[0]["kind"] == "seated"


# ---------- guests leave ----------


async def test_left_tells_the_waiter_and_flags_an_open_table(client: httpx.AsyncClient, emitted: list) -> None:
    _, h, branch, tables, (rohan, rid), (priya, _), agent = await _floor(client)

    # Free table: "T2 is empty". A second "left" is ignored.
    await client.post(f"{A}/events", json={"events": [_event("seated", "T2")]}, headers=agent)
    left = await client.post(f"{A}/events", json={"events": [_event("left", "T2")]}, headers=agent)
    assert left.json()["results"][0]["status"] == "ok"
    assert [a["kind"] for a in await _mine(client, priya, branch)] == ["seated_unchecked", "left"]
    repeat = await client.post(f"{A}/events", json={"events": [_event("left", "T2")]}, headers=agent)
    assert repeat.json()["results"][0]["status"] == "ignored"

    # Table still open in the app: the waiter is told to check the bill and the owner is told too.
    await _seat(client, h, tables["T1"])
    await client.post(f"{A}/events", json={"events": [_event("seated", "T1")]}, headers=agent)
    await client.post(f"{A}/events", json={"events": [_event("left", "T1")]}, headers=agent)
    kinds = [(a["kind"]) for a in await _mine(client, rohan, branch)]
    assert kinds == ["seated", "left_open"]
    owner_alerts = await _mine(client, h, branch)
    assert [a["kind"] for a in owner_alerts] == ["left_open"] and "unpaid" in owner_alerts[0]["message"]
    assert not any(a["kind"] == "left_open" for a in await _mine(client, priya, branch))


async def test_stale_and_unknown_events(client: httpx.AsyncClient, emitted: list) -> None:
    _, h, branch, tables, (rohan, _), _, agent = await _floor(client)
    old = datetime.now(UTC) - timedelta(minutes=30)  # the laptop was offline: remember it, do not ping anyone
    r = await client.post(f"{A}/events", json={"events": [_event("seated", "T1", at=old)]}, headers=agent)
    assert r.json()["results"][0]["status"] == "recorded_late" and not emitted
    unknown = await client.post(f"{A}/events", json={"events": [_event("seated", "T99")]}, headers=agent)
    assert unknown.json()["results"][0]["status"] == "unknown_table"
    bad = await client.post(
        f"{A}/events", json={"events": [{**_event("seated", "T1"), "kind": "exploded"}]}, headers=agent
    )
    assert bad.status_code == 422


async def test_an_agent_only_ever_touches_its_own_restaurant(client: httpx.AsyncClient, emitted: list) -> None:
    _, _, branch_a, _, (rohan, _), _, agent_a = await _floor(client)
    tenant_b, hb, branch_b, tables_b = await _setup(client, name="Other Bistro")  # also has a "T1"
    waiter_b, _ = await _waiter(client, hb, branch_b)
    await client.post(f"{A}/events", json={"events": [_event("seated", "T1")]}, headers=agent_a)
    assert await _mine(client, hb, branch_b) == [] and await _mine(client, waiter_b, branch_b) == []
    assert len(await _mine(client, rohan, branch_a)) == 1
    # And a waiter of restaurant B cannot read restaurant A's alerts.
    cross = await client.get(f"{B}/floor-alerts", params={"branch_id": branch_a["id"]}, headers=waiter_b)
    assert cross.status_code == 403 or cross.json() == []
