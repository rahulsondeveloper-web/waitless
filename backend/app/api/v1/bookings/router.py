"""Guest side of the queue and reservations (PRD §12), plus payment webhooks and the dev mock checkout."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import ClientDep, CurrentUser, SessionDep, feature_enabled
from app.core.config import get_settings
from app.core.db import use_system
from app.core.errors import AppError, NotFoundError
from app.integrations.payments.gateway import MockGateway, get_gateway
from app.models import Tenant
from app.models.booking import Reservation, ReservationPayment
from app.schemas.booking import (
    Availability,
    BookingOptions,
    BookingResult,
    CheckoutOut,
    MyBookings,
    QueueEntryOut,
    QueueJoinIn,
    ReservationIn,
    ReservationOut,
    WaitTime,
)
from app.services import queue as queue_svc
from app.services import reservations as res_svc
from app.services.profile import _public_tenant

router = APIRouter(tags=["bookings"])
Slug = Annotated[str, Path(min_length=2, max_length=60)]


async def _gate(session: SessionDep, tenant: Tenant, feature: str) -> None:
    if not await feature_enabled(session, tenant.id, feature):
        raise AppError("This restaurant does not offer this online.", code="FEATURE_UNAVAILABLE", status_code=404)


# ---------- public (no sign-in) ----------


@router.get("/public/restaurants/{slug}/booking-options", response_model=list[BookingOptions], summary="Per branch")
async def booking_options(slug: Slug, session: SessionDep) -> list[BookingOptions]:
    tenant = await _public_tenant(session, slug)
    out = await res_svc.options(session, tenant)
    if not await feature_enabled(session, tenant.id, "reservations"):
        out = [o.model_copy(update={"accepts_reservations": False}) for o in out]
    if not await feature_enabled(session, tenant.id, "reservations.paid"):
        out = [o.model_copy(update={"paid_enabled": False}) for o in out]
    if not await feature_enabled(session, tenant.id, "queue"):
        out = [o.model_copy(update={"accepts_queue": False}) for o in out]
    return out


@router.get("/public/restaurants/{slug}/availability", response_model=Availability, summary="Bookable time slots")
async def availability(
    slug: Slug,
    session: SessionDep,
    branch_id: uuid.UUID,
    day: date = Query(alias="date"),
    party: int = Query(default=2, ge=1, le=50),
) -> Availability:
    tenant = await _public_tenant(session, slug)
    await _gate(session, tenant, "reservations")
    branch = await res_svc.public_branch(session, branch_id)
    return await res_svc.availability(session, tenant, branch, day, party)


@router.get("/public/restaurants/{slug}/wait-time", response_model=WaitTime, summary="Live queue length & wait")
async def wait_time(
    slug: Slug, session: SessionDep, branch_id: uuid.UUID, party: int = Query(default=2, ge=1, le=50)
) -> WaitTime:
    tenant = await _public_tenant(session, slug)
    await _gate(session, tenant, "queue")
    return await queue_svc.wait_time(session, await res_svc.public_branch(session, branch_id), party)


# ---------- guest (signed in) ----------


@router.post("/public/restaurants/{slug}/queue", response_model=QueueEntryOut, status_code=201, summary="Join queue")
async def join_queue(
    slug: Slug, body: QueueJoinIn, session: SessionDep, user: CurrentUser, client: ClientDep
) -> QueueEntryOut:
    """With `seat_now: true` the guest may be seated at once (`seated_now` has the table, order ID, PIN and
    table token) when a free table suits the party and nobody waiting fits it."""
    tenant = await _public_tenant(session, slug)
    await _gate(session, tenant, "queue")
    return await queue_svc.join(session, tenant, user, body, client.ip)


@router.post(
    "/public/restaurants/{slug}/reservations", response_model=BookingResult, status_code=201, summary="Book a table"
)
async def book(slug: Slug, body: ReservationIn, session: SessionDep, user: CurrentUser) -> BookingResult:
    tenant = await _public_tenant(session, slug)
    await _gate(session, tenant, "reservations")
    if body.type == "paid":
        await _gate(session, tenant, "reservations.paid")
    return await res_svc.book(session, tenant, user, body)


@router.get("/me/bookings", response_model=MyBookings, summary="My reservations and queue tokens (all restaurants)")
async def my_bookings(session: SessionDep, user: CurrentUser) -> MyBookings:
    return MyBookings(
        reservations=await res_svc.my_reservations(session, user), queue=await queue_svc.my_entries(session, user)
    )


@router.get("/me/queue/{entry_id}", response_model=QueueEntryOut, summary="My queue token (live position)")
async def my_queue_entry(entry_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> QueueEntryOut:
    return await queue_svc.my_entry(session, user, entry_id)


@router.post("/me/queue/{entry_id}/leave", response_model=QueueEntryOut, summary="Leave the queue")
async def leave_queue(entry_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> QueueEntryOut:
    return await queue_svc.leave(session, user, entry_id)


@router.get("/me/reservations/{reservation_id}", response_model=ReservationOut, summary="My booking")
async def my_reservation(reservation_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ReservationOut:
    return await res_svc.my_reservation(session, user, reservation_id)


@router.post("/me/reservations/{reservation_id}/cancel", response_model=ReservationOut, summary="Cancel my booking")
async def cancel_reservation(reservation_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ReservationOut:
    return await res_svc.cancel_by_guest(session, user, reservation_id)


@router.post("/me/reservations/{reservation_id}/pay", response_model=CheckoutOut, summary="Retry the booking payment")
async def pay_reservation(reservation_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> CheckoutOut:
    return await res_svc.retry_payment(session, user, reservation_id)


# ---------- payment webhooks (server-to-server) ----------


class WebhookAck(BaseModel):
    result: str


@router.post("/webhooks/payments/{provider}", response_model=WebhookAck, summary="Payment provider webhook")
async def payment_webhook(
    provider: str,
    request: Request,
    session: SessionDep,
    x_webhook_signature: Annotated[str | None, Header()] = None,
    x_webhook_timestamp: Annotated[str | None, Header()] = None,
    x_mock_signature: Annotated[str | None, Header()] = None,
) -> WebhookAck:
    gateway = get_gateway(provider)
    body = await request.body()
    if provider == "cashfree":
        event = gateway.parse_webhook(body, x_webhook_signature, x_webhook_timestamp)
    else:
        event = gateway.parse_webhook(body, x_mock_signature)
    return WebhookAck(result=await res_svc.process_payment_event(session, gateway.name, event))


# ---------- mock checkout (development only) ----------


class MockOrderOut(BaseModel):
    order_id: str
    amount: str
    currency: str
    status: str
    reservation_id: uuid.UUID
    reservation_code: str
    restaurant_name: str
    restaurant_slug: str


class MockPayIn(BaseModel):
    success: bool = True


def _dev_only() -> None:
    if get_settings().is_production or get_settings().payment_provider != "mock":
        raise NotFoundError("Not found.")


async def _mock_order(session: SessionDep, order_id: str) -> tuple[ReservationPayment, Reservation, Tenant]:
    _dev_only()
    await use_system(session)
    p = await session.scalar(
        select(ReservationPayment).where(
            ReservationPayment.provider == "mock", ReservationPayment.provider_order_id == order_id
        )
    )
    if p is None:
        raise NotFoundError("Payment not found.")
    r = await session.get(Reservation, p.reservation_id)
    t = await session.get(Tenant, p.tenant_id)
    assert r is not None and t is not None
    return p, r, t


@router.get("/public/payments/mock/{order_id}", response_model=MockOrderOut, summary="Dev mock checkout: order")
async def mock_order(order_id: str, session: SessionDep, user: CurrentUser) -> MockOrderOut:
    p, r, t = await _mock_order(session, order_id)
    if r.customer_id != user.id:
        raise NotFoundError("Payment not found.")
    return MockOrderOut(
        order_id=p.provider_order_id,
        amount=str(p.amount),
        currency=p.currency,
        status=p.status,
        reservation_id=r.id,
        reservation_code=r.code,
        restaurant_name=t.name,
        restaurant_slug=t.slug,
    )


@router.post("/public/payments/mock/{order_id}", response_model=WebhookAck, summary="Dev mock checkout: pay/fail")
async def mock_pay(order_id: str, body: MockPayIn, session: SessionDep, user: CurrentUser) -> WebhookAck:
    """Simulates the provider: builds a signed webhook and feeds it through the same verified path."""
    p, r, _ = await _mock_order(session, order_id)
    if r.customer_id != user.id:
        raise NotFoundError("Payment not found.")
    raw, signature = MockGateway.build_event(p.provider_order_id, p.amount, body.success)
    event = MockGateway().parse_webhook(raw, signature)
    return WebhookAck(result=await res_svc.process_payment_event(session, "mock", event))
