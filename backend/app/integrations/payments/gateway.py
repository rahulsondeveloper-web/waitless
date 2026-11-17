"""Payment gateway interface (decision D17) with a mock and a Razorpay implementation.

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
class PaymentEvent:
    type: EventType
    order_id: str
    payment_id: str | None
    amount: Decimal


class PaymentGateway(Protocol):
    name: str

    async def create_order(
        self, amount: Decimal, currency: str, receipt: str, notes: dict[str, str]
    ) -> GatewayOrder: ...

    def parse_webhook(self, body: bytes, signature: str | None) -> PaymentEvent: ...

    async def refund(self, payment_id: str, amount: Decimal) -> str: ...


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

    async def create_order(self, amount: Decimal, currency: str, receipt: str, notes: dict[str, str]) -> GatewayOrder:
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

    def parse_webhook(self, body: bytes, signature: str | None) -> PaymentEvent:
        if not signature or not hmac.compare_digest(self.sign(body), signature):
            raise InvalidSignatureError("Webhook signature does not match.")
        data = json.loads(body)
        return PaymentEvent(
            type=data["event"],
            order_id=data["order_id"],
            payment_id=data.get("payment_id"),
            amount=Decimal(data["amount"]) / 100,
        )

    async def refund(self, payment_id: str, amount: Decimal) -> str:
        return f"mock_refund_{secrets.token_hex(8)}"


# ---------- Razorpay ----------


class RazorpayGateway:
    """https://razorpay.com/docs/api/ — orders, webhook signature (HMAC-SHA256 of the raw body), refunds."""

    name = "razorpay"
    base_url = "https://api.razorpay.com/v1"

    def __init__(self) -> None:
        s = get_settings()
        if not (s.razorpay_key_id and s.razorpay_key_secret and s.razorpay_webhook_secret):
            raise AppError("Online payments are not configured.", code="PAYMENTS_NOT_CONFIGURED", status_code=503)
        self.key_id, self.key_secret, self.webhook_secret = (
            s.razorpay_key_id,
            s.razorpay_key_secret,
            s.razorpay_webhook_secret,
        )

    def _auth(self) -> dict[str, str]:
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    async def create_order(self, amount: Decimal, currency: str, receipt: str, notes: dict[str, str]) -> GatewayOrder:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self.base_url}/orders",
                headers=self._auth(),
                json={"amount": _paise(amount), "currency": currency, "receipt": receipt[:40], "notes": notes},
            )
        if r.status_code >= 300:
            raise AppError(
                "The payment provider is unavailable. Please try again.", code="GATEWAY_ERROR", status_code=502
            )
        order = r.json()
        return GatewayOrder(
            provider=self.name,
            order_id=order["id"],
            amount=amount,
            currency=currency,
            checkout={"key_id": self.key_id, "order_id": order["id"], "amount": order["amount"], "currency": currency},
        )

    def parse_webhook(self, body: bytes, signature: str | None) -> PaymentEvent:
        if not signature or not hmac.compare_digest(_hmac(self.webhook_secret, body), signature):
            raise InvalidSignatureError("Webhook signature does not match.")
        data = json.loads(body)
        entity = data.get("payload", {}).get("payment", {}).get("entity", {})
        event = data.get("event")
        if event not in ("payment.captured", "payment.failed"):
            raise AppError("Event ignored.", code="EVENT_IGNORED", status_code=202)
        return PaymentEvent(
            type=event,
            order_id=entity.get("order_id", ""),
            payment_id=entity.get("id"),
            amount=Decimal(entity.get("amount", 0)) / 100,
        )

    async def refund(self, payment_id: str, amount: Decimal) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self.base_url}/payments/{payment_id}/refund", headers=self._auth(), json={"amount": _paise(amount)}
            )
        if r.status_code >= 300:
            raise AppError("Refund failed at the payment provider.", code="REFUND_FAILED", status_code=502)
        return r.json()["id"]


def get_gateway(name: str | None = None) -> PaymentGateway:
    provider = name or get_settings().payment_provider
    if provider == "mock":
        if get_settings().is_production:
            raise AppError("Mock payments are disabled in production.", code="PAYMENTS_NOT_CONFIGURED", status_code=503)
        return MockGateway()
    if provider == "razorpay":
        return RazorpayGateway()
    raise AppError("Unknown payment provider.", code="UNKNOWN_PROVIDER", status_code=404)
