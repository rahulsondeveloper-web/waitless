"""Cashfree payment gateway adapter — orders, webhook signatures and refunds, without network access."""

import base64
import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.payments import gateway as gw
from app.integrations.payments.gateway import CashfreeGateway, Customer, InvalidSignatureError, get_gateway


@pytest.fixture
def cashfree(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        payment_provider="cashfree",
        cashfree_app_id="TEST_APP",
        cashfree_secret_key="cfsk_test_secret",
        cashfree_env="sandbox",
        public_base_url="https://waitless.app",
    )
    monkeypatch.setattr(gw, "get_settings", lambda: s)
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/pg/orders":
            body = json.loads(req.content)
            return httpx.Response(200, json={"order_id": body["order_id"], "payment_session_id": "session_abc"})
        if req.url.path.endswith("/refunds"):
            return httpx.Response(
                200, json={"cf_refund_id": "cfr_1", "refund_id": json.loads(req.content)["refund_id"]}
            )
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(gw.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls


async def test_creates_an_order_with_customer_and_notify_url(cashfree: list[httpx.Request]) -> None:
    g = get_gateway()
    assert isinstance(g, CashfreeGateway)
    order = await g.create_order(
        Decimal("611.5"), "INR", "bill-1", {"bill_id": "b1"}, customer=Customer(id="u1", phone="+919812345678")
    )
    req = cashfree[-1]
    assert req.url.host == "sandbox.cashfree.com"
    assert req.headers["x-client-id"] == "TEST_APP" and req.headers["x-api-version"] == "2023-08-01"
    body = json.loads(req.content)
    assert body["order_amount"] == 611.5 and body["order_currency"] == "INR"
    assert body["customer_details"] == {"customer_id": "u1", "customer_phone": "9812345678"}
    assert body["order_meta"]["notify_url"] == "https://waitless.app/api/v1/webhooks/payments/cashfree"
    assert order.provider == "cashfree" and order.order_id == body["order_id"]
    assert order.checkout == {
        "provider": "cashfree",
        "payment_session_id": "session_abc",
        "order_id": order.order_id,
        "mode": "sandbox",
    }


async def test_walk_in_guest_without_phone_uses_the_fallback(cashfree: list[httpx.Request]) -> None:
    await get_gateway().create_order(Decimal("100"), "INR", "bill-2", {}, customer=Customer(id="table-1"))
    assert json.loads(cashfree[-1].content)["customer_details"]["customer_phone"] == "9999999999"


def _signed(body: bytes, ts: str = "1731900000000") -> tuple[bytes, str, str]:
    sig = base64.b64encode(hmac.new(b"cfsk_test_secret", ts.encode() + body, hashlib.sha256).digest()).decode()
    return body, sig, ts


def _event(kind: str, status: str) -> bytes:
    return json.dumps(
        {
            "type": kind,
            "data": {
                "order": {"order_id": "wl_abc", "order_amount": 611.5},
                "payment": {"cf_payment_id": 5114910, "payment_status": status, "payment_amount": 611.5},
            },
        }
    ).encode()


def test_webhook_signature_is_verified_and_events_are_mapped(cashfree: list[httpx.Request]) -> None:
    g = get_gateway()
    ev = g.parse_webhook(*_signed(_event("PAYMENT_SUCCESS_WEBHOOK", "SUCCESS")))
    assert (ev.type, ev.order_id, ev.payment_id, ev.amount) == (
        "payment.captured",
        "wl_abc",
        "5114910",
        Decimal("611.5"),
    )
    assert g.parse_webhook(*_signed(_event("PAYMENT_FAILED_WEBHOOK", "FAILED"))).type == "payment.failed"
    assert g.parse_webhook(*_signed(_event("PAYMENT_USER_DROPPED_WEBHOOK", "USER_DROPPED"))).type == "payment.failed"

    body, sig, ts = _signed(_event("PAYMENT_SUCCESS_WEBHOOK", "SUCCESS"))
    with pytest.raises(InvalidSignatureError):
        g.parse_webhook(body.replace(b"611.5", b"1.0"), sig, ts)  # tampered amount
    with pytest.raises(InvalidSignatureError):
        g.parse_webhook(body, sig, "1731900000001")  # different timestamp
    with pytest.raises(InvalidSignatureError):
        g.parse_webhook(body, None, ts)
    with pytest.raises(AppError) as err:
        g.parse_webhook(*_signed(json.dumps({"type": "REFUND_STATUS_WEBHOOK", "data": {}}).encode()))
    assert err.value.code == "EVENT_IGNORED"


async def test_refunds_are_made_against_the_order(cashfree: list[httpx.Request]) -> None:
    ref = await get_gateway().refund("wl_abc", "5114910", Decimal("100"))
    req = cashfree[-1]
    assert req.url.path == "/pg/orders/wl_abc/refunds"
    body = json.loads(req.content)
    assert body["refund_amount"] == 100.0 and body["refund_id"].startswith("wl_rf_")
    assert ref == "cfr_1"


def test_missing_keys_is_a_clear_503(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None, payment_provider="cashfree")  # type: ignore[call-arg]
    monkeypatch.setattr(gw, "get_settings", lambda: s)
    with pytest.raises(AppError) as err:
        get_gateway()
    assert err.value.code == "PAYMENTS_NOT_CONFIGURED"
