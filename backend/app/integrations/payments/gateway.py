"""Payment gateway interface (decision D17) with a mock and a Cashfree implementation.

Webhooks are the source of truth: a booking is confirmed only after a *verified* webhook says the
payment was captured (PRD §12 "Payment must be verified by the backend").
"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import AppError

EventType = Literal["payment.captured", "payment.failed"]


@dataclass(frozen=True)
class GatewayOrder:
    provider: str
    order_id: str
    amount: Decimal
    currency: str
    checkout: dict[str, Any]  # what the browser needs to open the checkout


@dataclass(frozen=True)
class Customer:
    """Who pays — Cashfree requires an ID and a phone number on every order."""

    id: str
    phone: str | None = None
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class PaymentEvent:
    type: EventType
    order_id: str
    payment_id: str | None
    amount: Decimal


class PaymentGateway(Protocol):
    name: str

    async def create_order(
        self,
        amount: Decimal,
        currency: str,
        receipt: str,
        notes: dict[str, str],
        customer: Customer | None = None,
    ) -> GatewayOrder: ...

    def parse_webhook(self, body: bytes, signature: str | None, timestamp: str | None = None) -> PaymentEvent: ...

    async def refund(self, order_id: str, payment_id: str | None, amount: Decimal) -> str: ...


def _paise(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _hmac(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class InvalidSignatureError(AppError):
    status_code = 400
    code = "INVALID_SIGNATURE"


# ---------- mock (development & tests) ----------


class MockGateway:
    """Behaves like a real gateway: orders, HMAC-signed webhooks, refunds — without leaving the machine."""

    name = "mock"

    async def create_order(
        self,
        amount: Decimal,
        currency: str,
        receipt: str,
        notes: dict[str, str],
        customer: Customer | None = None,
    ) -> GatewayOrder:
        order_id = f"mock_order_{secrets.token_hex(10)}"
        return GatewayOrder(
            provider=self.name,
            order_id=order_id,
            amount=amount,
            currency=currency,
            checkout={"url": f"/pay/mock/{order_id}"},
        )

    @staticmethod
    def sign(body: bytes) -> str:
        return _hmac(get_settings().mock_webhook_secret, body)

    @classmethod
    def build_event(cls, order_id: str, amount: Decimal, success: bool) -> tuple[bytes, str]:
        payload = {
            "event": "payment.captured" if success else "payment.failed",
            "order_id": order_id,
            "payment_id": f"mock_pay_{secrets.token_hex(10)}",
            "amount": _paise(amount),
        }
        body = json.dumps(payload).encode()
        return body, cls.sign(body)

    def parse_webhook(self, body: bytes, signature: str | None, timestamp: str | None = None) -> PaymentEvent:
        if not signature or not hmac.compare_digest(self.sign(body), signature):
            raise InvalidSignatureError("Webhook signature does not match.")
        data = json.loads(body)
        return PaymentEvent(
            type=data["event"],
            order_id=data["order_id"],
            payment_id=data.get("payment_id"),
            amount=Decimal(data["amount"]) / 100,
        )

    async def refund(self, order_id: str, payment_id: str | None, amount: Decimal) -> str:
        return f"mock_refund_{secrets.token_hex(8)}"


# ---------- Cashfree ----------


def _cashfree_phone(phone: str | None) -> str:
    """Cashfree wants a 10-digit Indian mobile number; E.164 "+9198…" is trimmed to its last 10 digits."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return get_settings().cashfree_fallback_phone


class CashfreeGateway:
    """https://docs.cashfree.com/reference/pg-new-apis-endpoint (API version 2023-08-01).

    Orders return a `payment_session_id` that the browser opens with Cashfree's JS SDK (UPI ID, UPI QR,
    cards, net banking, wallets). Webhooks are signed: base64(HMAC-SHA256(timestamp + raw body, secret key)).
    Refunds are made against our order ID.
    """

    name = "cashfree"
    api_version = "2023-08-01"

    def __init__(self) -> None:
        s = get_settings()
        if not (s.cashfree_app_id and s.cashfree_secret_key):
            raise AppError("Online payments are not configured.", code="PAYMENTS_NOT_CONFIGURED", status_code=503)
        self.app_id, self.secret_key, self.mode = s.cashfree_app_id, s.cashfree_secret_key, s.cashfree_env
        self.base_url = (
            "https://api.cashfree.com/pg" if self.mode == "production" else "https://sandbox.cashfree.com/pg"
        )
        self.public_base_url = s.public_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "x-client-id": self.app_id,
            "x-client-secret": self.secret_key,
            "x-api-version": self.api_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_order(
        self,
        amount: Decimal,
        currency: str,
        receipt: str,
        notes: dict[str, str],
        customer: Customer | None = None,
    ) -> GatewayOrder:
        order_id = f"wl_{secrets.token_hex(12)}"  # ours, unique; Cashfree allows [A-Za-z0-9_-], max 45
        body: dict[str, Any] = {
            "order_id": order_id,
            "order_amount": float(amount.quantize(Decimal("0.01"))),
            "order_currency": currency,
            "customer_details": {
                "customer_id": (customer.id if customer else "guest")[:50],
                "customer_phone": _cashfree_phone(customer.phone if customer else None),
            },
            "order_note": receipt[:200],
            # tags: short strings only (they come back in webhooks and the dashboard)
            "order_tags": {k[:32]: str(v)[:64] for k, v in list(notes.items())[:10]},
        }
        if customer and customer.name:
            body["customer_details"]["customer_name"] = customer.name[:100]
        if customer and customer.email:
            body["customer_details"]["customer_email"] = customer.email[:100]
        if self.public_base_url.startswith("https://"):  # Cashfree only calls https URLs
            body["order_meta"] = {"notify_url": f"{self.public_base_url}/api/v1/webhooks/payments/cashfree"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{self.base_url}/orders", headers=self._headers(), json=body)
        if r.status_code >= 300:
            raise AppError(
                "The payment provider is unavailable. Please try again.", code="GATEWAY_ERROR", status_code=502
            )
        order = r.json()
        return GatewayOrder(
            provider=self.name,
            order_id=order["order_id"],
            amount=amount,
            currency=currency,
            checkout={
                "provider": self.name,
                "payment_session_id": order["payment_session_id"],
                "order_id": order["order_id"],
                "mode": self.mode,
            },
        )

    def signature(self, body: bytes, timestamp: str) -> str:
        mac = hmac.new(self.secret_key.encode(), timestamp.encode() + body, hashlib.sha256).digest()
        return base64.b64encode(mac).decode()

    def parse_webhook(self, body: bytes, signature: str | None, timestamp: str | None = None) -> PaymentEvent:
        if not signature or not timestamp or not hmac.compare_digest(self.signature(body, timestamp), signature):
            raise InvalidSignatureError("Webhook signature does not match.")
        data = json.loads(body)
        kind = data.get("type")
        payload = data.get("data") or {}
        order = payload.get("order") or {}
        payment = payload.get("payment") or {}
        if kind == "PAYMENT_SUCCESS_WEBHOOK" and payment.get("payment_status") == "SUCCESS":
            event: EventType = "payment.captured"
        elif kind in ("PAYMENT_FAILED_WEBHOOK", "PAYMENT_USER_DROPPED_WEBHOOK"):
            event = "payment.failed"
        else:
            raise AppError("Event ignored.", code="EVENT_IGNORED", status_code=202)
        cf_payment_id = payment.get("cf_payment_id")
        return PaymentEvent(
            type=event,
            order_id=str(order.get("order_id", "")),
            payment_id=str(cf_payment_id) if cf_payment_id is not None else None,
            amount=Decimal(str(payment.get("payment_amount", order.get("order_amount", 0)))),
        )

    async def refund(self, order_id: str, payment_id: str | None, amount: Decimal) -> str:
        refund_id = f"wl_rf_{secrets.token_hex(10)}"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self.base_url}/orders/{order_id}/refunds",
                headers=self._headers(),
                json={
                    "refund_amount": float(amount.quantize(Decimal("0.01"))),
                    "refund_id": refund_id,
                    "refund_note": "WaitLess refund",
                },
            )
        if r.status_code >= 300:
            raise AppError("Refund failed at the payment provider.", code="REFUND_FAILED", status_code=502)
        data = r.json()
        return str(data.get("cf_refund_id") or data.get("refund_id") or refund_id)


def get_gateway(name: str | None = None) -> PaymentGateway:
    provider = name or get_settings().payment_provider
    if provider == "mock":
        if get_settings().is_production:
            raise AppError("Mock payments are disabled in production.", code="PAYMENTS_NOT_CONFIGURED", status_code=503)
        return MockGateway()
    if provider == "cashfree":
        return CashfreeGateway()
    raise AppError("Unknown payment provider.", code="UNKNOWN_PROVIDER", status_code=404)
