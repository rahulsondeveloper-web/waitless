"""Phase 5: branches, employees, roles, tables, table sessions, dashboard, live-room authorisation."""

import asyncio
import re
import uuid

import httpx
import pytest

from app.websocket.server import authorize_branch_room
from tests.conftest import bearer, login, random_mobile, register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]

B = "/api/v1/restaurant"


async def _owner(client: httpx.AsyncClient, **kw):  # type: ignore[no-untyped-def]
    tenant, payload = await register(client, **kw)
    auth = await login(client, payload["email"])
    return tenant, bearer(auth), auth


async def _primary_branch(client: httpx.AsyncClient, h: dict) -> dict:
    return (await client.get(f"{B}/branches", headers=h)).json()[0]


async def _roles(client: httpx.AsyncClient, h: dict) -> dict[str, dict]:
    return {r["key"]: r for r in (await client.get(f"{B}/roles", headers=h)).json()}


async def _otp_login(client: httpx.AsyncClient, mobile: str) -> dict:
    code = (await client.post("/api/v1/auth/otp/send", json={"phone": mobile})).json()["dev_code"]
    r = await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


async def _second_branch(client: httpx.AsyncClient, h: dict, name: str = "Second Branch") -> dict:
    r = await client.post(
        f"{B}/branches",
        json={"name": name, "address_line": "99 Other Road", "city": "Mumbai", "state": "MH"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- branches ----------


async def test_branches_create_limit_and_rules(client: httpx.AsyncClient) -> None:
    _, h, _ = await _owner(client)
    primary = await _primary_branch(client, h)
    for i in range(4):  # Professional trial allows 5 branches
        await _second_branch(client, h, f"Branch {i}")
    sixth = await client.post(
        f"{B}/branches",
        json={"name": "Too Many", "address_line": "1 Road Street", "city": "Pune", "state": "MH"},
        headers=h,
    )
    assert sixth.status_code == 409 and sixth.json()["error"]["code"] == "PLAN_LIMIT_REACHED"
    assert sixth.json()["error"]["details"]["limit"] == 5

    no = await client.patch(f"{B}/branches/{primary['id']}/status", json={"is_active": False}, headers=h)
    assert no.status_code == 409 and no.json()["error"]["code"] == "PRIMARY_BRANCH"
    bad_tz = await client.post(
        f"{B}/branches",
        json={"name": "X", "address_line": "1 Road Street", "city": "Pune", "state": "MH", "timezone": "Mars/Base"},
        headers=h,
    )
    assert bad_tz.status_code == 422


# ---------- staff & roles ----------


async def test_invite_waiter_who_signs_in_with_otp(client: httpx.AsyncClient) -> None:
    tenant, h, _ = await _owner(client)
    branch = await _primary_branch(client, h)
    roles = await _roles(client, h)
    mobile = random_mobile()

    invited = await client.post(
        f"{B}/staff",
        json={
            "full_name": "Ravi Waiter",
            "phone": mobile,
            "role_id": roles["waiter"]["id"],
            "branch_ids": [branch["id"]],
        },
        headers=h,
    )
    assert invited.status_code == 201, invited.text
    staff = invited.json()
    assert staff["role_key"] == "waiter" and staff["branch_ids"] == [branch["id"]] and not staff["is_owner"]

    again = await client.post(
        f"{B}/staff",
        json={"full_name": "Ravi", "phone": mobile, "role_id": roles["waiter"]["id"], "branch_ids": [branch["id"]]},
        headers=h,
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_STAFF"

    waiter = await _otp_login(client, mobile)
    active = waiter["me"]["active_tenant"]
    assert active["tenant_id"] == tenant["id"] and active["role_key"] == "waiter"
    wh = bearer(waiter)
    assert (await client.get(f"{B}/tables/board", params={"branch_id": branch["id"]}, headers=wh)).status_code == 200
    assert (await client.get(f"{B}/menu", headers=wh)).status_code == 403  # no menu.manage
    assert (await client.get(f"{B}/staff", headers=wh)).status_code == 403

    # Disabled staff lose access immediately.
    await client.patch(f"{B}/staff/{staff['membership_id']}", json={"status": "disabled"}, headers=h)
    blocked = await client.get(f"{B}/tables/board", params={"branch_id": branch["id"]}, headers=wh)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "NOT_A_MEMBER"


async def test_staff_rules_owner_self_and_manager_scope(client: httpx.AsyncClient) -> None:
    _, h, owner_auth = await _owner(client)
    b1 = await _primary_branch(client, h)
    b2 = await _second_branch(client, h)
    roles = await _roles(client, h)

    owner_role = await client.post(
        f"{B}/staff",
        json={"full_name": "Xavier", "phone": random_mobile(), "role_id": roles["owner"]["id"], "all_branches": True},
        headers=h,
    )
    assert owner_role.status_code == 403 and owner_role.json()["error"]["code"] == "ROLE_NOT_ASSIGNABLE"

    me = next(s for s in (await client.get(f"{B}/staff", headers=h)).json() if s["is_you"])
    assert me["is_owner"]
    assert (
        await client.patch(f"{B}/staff/{me['membership_id']}", json={"status": "disabled"}, headers=h)
    ).status_code == 403

    manager_mobile = random_mobile()
    await client.post(
        f"{B}/staff",
        json={
            "full_name": "Meera Manager",
            "phone": manager_mobile,
            "role_id": roles["manager"]["id"],
            "branch_ids": [b1["id"]],
        },
        headers=h,
    )
    mh = bearer(await _otp_login(client, manager_mobile))

    ok = await client.post(
        f"{B}/staff",
        json={
            "full_name": "Cook",
            "phone": random_mobile(),
            "role_id": roles["kitchen"]["id"],
            "branch_ids": [b1["id"]],
        },
        headers=mh,
    )
    assert ok.status_code == 201
    other_branch = await client.post(
        f"{B}/staff",
        json={
            "full_name": "Cook 2",
            "phone": random_mobile(),
            "role_id": roles["kitchen"]["id"],
            "branch_ids": [b2["id"]],
        },
        headers=mh,
    )
    assert other_branch.status_code == 403 and other_branch.json()["error"]["code"] == "BRANCH_FORBIDDEN"
    promote = await client.post(
        f"{B}/staff",
        json={
            "full_name": "Boss",
            "phone": random_mobile(),
            "role_id": roles["manager"]["id"],
            "branch_ids": [b1["id"]],
        },
        headers=mh,
    )
    assert promote.status_code == 403
    assert (
        await client.post(
            f"{B}/branches",
            json={"name": "Nope", "address_line": "1 Road Street", "city": "Pune", "state": "MH"},
            headers=mh,
        )
    ).status_code == 403
    # Manager sees only staff of their branch (not the all-branches owner).
    visible = {s["full_name"] for s in (await client.get(f"{B}/staff", headers=mh)).json()}
    assert visible == {"Meera Manager", "Cook"}
    assert owner_auth["me"]["user"]["full_name"] not in visible


async def test_custom_roles(client: httpx.AsyncClient) -> None:
    _, h, _ = await _owner(client)
    branch = await _primary_branch(client, h)
    created = await client.post(
        f"{B}/roles",
        json={"name": "Host", "permissions": {"tables.operate": "own_branches", "queue.manage": "own_branches"}},
        headers=h,
    )
    assert created.status_code == 201, created.text
    host = created.json()
    assert host["key"] == "custom_host" and not host["is_system"]

    unknown = await client.post(f"{B}/roles", json={"name": "Bad", "permissions": {"launch.rockets": "all"}}, headers=h)
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNKNOWN_PERMISSION"
    billing = await client.post(
        f"{B}/roles", json={"name": "Acc", "permissions": {"subscription.manage": "all"}}, headers=h
    )
    assert billing.status_code == 403

    mobile = random_mobile()
    await client.post(
        f"{B}/staff",
        json={"full_name": "Hina Host", "phone": mobile, "role_id": host["id"], "branch_ids": [branch["id"]]},
        headers=h,
    )
    hh = bearer(await _otp_login(client, mobile))
    assert (await client.get(f"{B}/tables/board", params={"branch_id": branch["id"]}, headers=hh)).status_code == 200

    in_use = await client.delete(f"{B}/roles/{host['id']}", headers=h)
    assert in_use.status_code == 409 and in_use.json()["error"]["code"] == "ROLE_IN_USE"
    system = (await _roles(client, h))["waiter"]
    assert (await client.patch(f"{B}/roles/{system['id']}", json={"name": "Server"}, headers=h)).status_code == 403
    perms = (await client.get(f"{B}/permissions", headers=h)).json()
    assert any(p["key"] == "tables.operate" for p in perms)


# ---------- tables & sessions ----------


async def _floor(client: httpx.AsyncClient, h: dict) -> tuple[dict, dict, dict]:
    branch = await _primary_branch(client, h)
    section = (
        await client.post(f"{B}/sections", json={"branch_id": branch["id"], "name": "Terrace"}, headers=h)
    ).json()
    t1 = (
        await client.post(
            f"{B}/tables",
            json={"branch_id": branch["id"], "section_id": section["id"], "label": "T1", "capacity": 4},
            headers=h,
        )
    ).json()
    t2 = (
        await client.post(f"{B}/tables", json={"branch_id": branch["id"], "label": "T2", "capacity": 2}, headers=h)
    ).json()
    return branch, t1, t2


async def test_table_lifecycle(client: httpx.AsyncClient) -> None:
    tenant, h, _ = await _owner(client, restaurant_name="Urban Bites Test")
    branch, t1, t2 = await _floor(client, h)

    dup = await client.post(f"{B}/tables", json={"branch_id": branch["id"], "label": "t1", "capacity": 2}, headers=h)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_LABEL"

    seated = await client.post(
        f"{B}/table-sessions", json={"table_id": t1["id"], "party_size": 3, "guest_name": "Sharma"}, headers=h
    )
    assert seated.status_code == 201, seated.text
    body = seated.json()
    assert re.fullmatch(r"UB-\d{4}", body["session"]["public_code"]) and re.fullmatch(r"\d{4}", body["pin"])
    assert body["session"]["table_ids"] == [t1["id"]]

    again = await client.post(f"{B}/table-sessions", json={"table_id": t1["id"], "party_size": 2}, headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "TABLE_ALREADY_ASSIGNED"

    board = (await client.get(f"{B}/tables/board", params={"branch_id": branch["id"]}, headers=h)).json()
    row = next(t for t in board["tables"] if t["id"] == t1["id"])
    assert row["status"] == "occupied" and row["section_name"] == "Terrace" and row["session"]["guest_name"] == "Sharma"
    assert board["counts"] == {"available": 1, "reserved": 0, "occupied": 1, "cleaning": 0}

    dash = (await client.get(f"{B}/dashboard", headers=h)).json()
    assert dash["open_sessions"] == 1 and dash["guests_seated"] == 3 and dash["tables_total"] == 2
    assert dash["orders_today"] is None  # arrives with ordering

    bad = await client.patch(f"{B}/tables/{t1['id']}/status", json={"status": "reserved"}, headers=h)
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "INVALID_TABLE_STATUS"
    assert (await client.patch(f"{B}/tables/{t1['id']}", json={"is_active": False}, headers=h)).status_code == 409

    sid = body["session"]["id"]
    moved = (await client.post(f"{B}/table-sessions/{sid}/transfer", json={"table_id": t2["id"]}, headers=h)).json()
    assert moved["table_ids"] == [t2["id"]]
    statuses = {
        t["id"]: t["status"]
        for t in (await client.get(f"{B}/tables", params={"branch_id": branch["id"]}, headers=h)).json()
    }
    assert statuses == {t1["id"]: "cleaning", t2["id"]: "occupied"}

    pin2 = (await client.post(f"{B}/table-sessions/{sid}/pin", headers=h)).json()["pin"]
    assert re.fullmatch(r"\d{4}", pin2)

    closed = (await client.post(f"{B}/table-sessions/{sid}/close", headers=h)).json()
    assert closed["status"] == "closed" and closed["table_ids"] == []
    assert (await client.post(f"{B}/table-sessions/{sid}/close", headers=h)).status_code == 409
    cleaned = await client.patch(f"{B}/tables/{t2['id']}/status", json={"status": "available"}, headers=h)
    assert cleaned.json()["status"] == "available"


async def test_concurrent_seating_has_exactly_one_winner(client: httpx.AsyncClient) -> None:
    """PRD §11 / test 17: two waiters seat the same table at the same moment."""
    _, h, _ = await _owner(client)
    _, t1, _ = await _floor(client, h)
    results = await asyncio.gather(
        *[client.post(f"{B}/table-sessions", json={"table_id": t1["id"], "party_size": 2}, headers=h) for _ in range(5)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409], [r.text for r in results]


async def test_tables_are_private_per_restaurant(client: httpx.AsyncClient) -> None:
    _, ha, _ = await _owner(client, restaurant_name="Alpha Tables")
    branch_a, t1, _ = await _floor(client, ha)
    _, hb, _ = await _owner(client, restaurant_name="Beta Tables")
    assert (
        await client.post(f"{B}/table-sessions", json={"table_id": t1["id"], "party_size": 2}, headers=hb)
    ).status_code == 404
    assert (await client.get(f"{B}/tables/board", params={"branch_id": branch_a["id"]}, headers=hb)).status_code == 404
    assert (
        await client.post(f"{B}/tables", json={"branch_id": branch_a["id"], "label": "X", "capacity": 2}, headers=hb)
    ).status_code == 404


async def test_waiter_limited_to_own_branch(client: httpx.AsyncClient) -> None:
    _, h, _ = await _owner(client)
    b1, t1, _ = await _floor(client, h)
    b2 = await _second_branch(client, h)
    roles = await _roles(client, h)
    mobile = random_mobile()
    inv = await client.post(
        f"{B}/staff",
        json={"full_name": "Wasim Waiter", "phone": mobile, "role_id": roles["waiter"]["id"], "branch_ids": [b2["id"]]},
        headers=h,
    )
    assert inv.status_code == 201, inv.text
    wh = bearer(await _otp_login(client, mobile))
    r = await client.post(f"{B}/table-sessions", json={"table_id": t1["id"], "party_size": 2}, headers=wh)
    assert r.status_code == 403 and r.json()["error"]["code"] == "BRANCH_FORBIDDEN"
    assert (await client.get(f"{B}/tables/board", params={"branch_id": b1["id"]}, headers=wh)).status_code == 403


async def test_live_room_authorisation(client: httpx.AsyncClient) -> None:
    tenant_a, ha, auth_a = await _owner(client, restaurant_name="Room A")
    branch_a = await _primary_branch(client, ha)
    tenant_b, hb, auth_b = await _owner(client, restaurant_name="Room B")
    user_a = uuid.UUID(auth_a["me"]["user"]["id"])
    user_b = uuid.UUID(auth_b["me"]["user"]["id"])
    a, ba = uuid.UUID(tenant_a["id"]), uuid.UUID(branch_a["id"])
    assert await authorize_branch_room(user_a, a, ba) is True
    assert await authorize_branch_room(user_b, a, ba) is False  # not a member of A
    assert await authorize_branch_room(user_b, uuid.UUID(tenant_b["id"]), ba) is False  # A's branch via B's tenant


async def test_publish_checklist_requires_a_table(client: httpx.AsyncClient) -> None:
    _, h, _ = await _owner(client)
    items = {i["key"]: i for i in (await client.get(f"{B}/publish-checklist", headers=h)).json()["items"]}
    assert items["tables"]["required"] and not items["tables"]["done"]
    await _floor(client, h)
    items = {i["key"]: i for i in (await client.get(f"{B}/publish-checklist", headers=h)).json()["items"]}
    assert items["tables"]["done"]
