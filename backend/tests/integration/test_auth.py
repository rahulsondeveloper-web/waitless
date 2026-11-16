import httpx
import pytest

from tests.conftest import PASSWORD, bearer, create_super_admin, login, random_mobile, register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("db")]


async def test_super_admin_password_login_and_me(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    auth = await login(client, "ADMIN@waitless.test")  # email is case-insensitive
    assert auth["me"]["user"]["is_super_admin"] is True
    assert auth["me"]["active_tenant"] is None
    assert "wl_refresh" in client.cookies

    r = await client.get("/api/v1/me", headers=bearer(auth))
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "admin@waitless.test"


async def test_wrong_password_is_generic_and_rate_limited(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", json={"identifier": "admin@waitless.test", "password": "nope"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    r = await client.post("/api/v1/auth/login", json={"identifier": "admin@waitless.test", "password": PASSWORD})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"


async def test_unknown_user_gets_same_error(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/auth/login", json={"identifier": "ghost@example.com", "password": "whatever1"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_owner_can_log_in_with_mobile_number(client: httpx.AsyncClient) -> None:
    _, payload = await register(client)
    auth = await login(client, payload["mobile"])
    assert auth["me"]["active_tenant"]["role_key"] == "owner"


async def test_customer_otp_flow_creates_account(client: httpx.AsyncClient) -> None:
    mobile = random_mobile()
    sent = await client.post("/api/v1/auth/otp/send", json={"phone": mobile})
    assert sent.status_code == 200
    body = sent.json()
    assert body["phone"] == f"+91{mobile}"
    code = body["dev_code"]
    assert code and len(code) == 6

    wrong = "000000" if code != "000000" else "111111"
    bad = await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": wrong})
    assert bad.json()["error"]["code"] == "OTP_INVALID"

    ok = await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code, "full_name": "Ravi"})
    assert ok.status_code == 200, ok.text
    me = ok.json()["me"]
    assert me["user"]["phone"] == f"+91{mobile}"
    assert me["user"]["full_name"] == "Ravi"
    assert me["memberships"] == []

    again = await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code})
    assert again.json()["error"]["code"] == "OTP_EXPIRED"  # one-time use


async def test_otp_send_is_rate_limited(client: httpx.AsyncClient) -> None:
    mobile = random_mobile()
    for _ in range(3):
        assert (await client.post("/api/v1/auth/otp/send", json={"phone": mobile})).status_code == 200
    r = await client.post("/api/v1/auth/otp/send", json={"phone": mobile})
    assert r.status_code == 429


async def test_otp_rejects_invalid_phone(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/auth/otp/send", json={"phone": "12345"})
    assert r.status_code == 422


async def test_refresh_rotates_and_detects_reuse(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    await login(client, "admin@waitless.test")
    first = client.cookies["wl_refresh"]

    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 200, r.text
    second = client.cookies["wl_refresh"]
    assert second != first
    assert r.json()["me"]["user"]["is_super_admin"] is True

    # Replaying the rotated (old) token = theft signal → whole family revoked.
    client.cookies.clear()
    replay = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"wl_refresh={first}"})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    after = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"wl_refresh={second}"})
    assert after.status_code == 401


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    await login(client, "admin@waitless.test")
    token = client.cookies["wl_refresh"]
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    r = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"wl_refresh={token}"})
    assert r.status_code == 401


async def test_super_admin_cannot_use_otp(client: httpx.AsyncClient) -> None:
    from app.core.db import get_sessionmaker, use_system
    from app.core.security import hash_password
    from app.models import User

    mobile = random_mobile()
    async with get_sessionmaker()() as s:
        await use_system(s)
        s.add(
            User(
                email="sa2@waitless.test",
                phone=f"+91{mobile}",
                password_hash=hash_password(PASSWORD),
                is_super_admin=True,
            )
        )
        await s.commit()
    code = (await client.post("/api/v1/auth/otp/send", json={"phone": mobile})).json()["dev_code"]
    r = await client.post("/api/v1/auth/otp/verify", json={"phone": mobile, "code": code})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"


async def test_invalid_or_missing_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/me")).json()["error"]["code"] == "NOT_AUTHENTICATED"
    r = await client.get("/api/v1/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_change_password_signs_out_other_sessions(client: httpx.AsyncClient) -> None:
    await create_super_admin()
    auth = await login(client, "admin@waitless.test")
    token = client.cookies["wl_refresh"]
    r = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "Brand-new-pass1"},
        headers=bearer(auth),
    )
    assert r.status_code == 204
    assert (await client.post("/api/v1/auth/refresh", headers={"Cookie": f"wl_refresh={token}"})).status_code == 401
    await login(client, "admin@waitless.test", "Brand-new-pass1")
