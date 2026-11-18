"""Guest ordering (PRD §13): table code + PIN, orders from the table, paid pre-orders, my orders."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Response
from pydantic import BaseModel, Field

from app.api.deps import ClientDep, CurrentUser, OptionalUser, SessionDep
from app.schemas.orders import OrderIn, OrderOut, TableJoinIn, TableJoinOut, TableSessionView
from app.services import orders as svc
from app.services.profile import _public_tenant

router = APIRouter(tags=["ordering"])
Slug = Annotated[str, Path(min_length=2, max_length=60)]
TableToken = Annotated[str | None, Header(alias="X-Table-Token", description="From POST …/table-sessions/join")]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)]


def _status(response: Response, created: bool) -> None:
    response.status_code = 201 if created else 200  # 200 = the original order (same Idempotency-Key)


@router.post(
    "/public/restaurants/{slug}/table-sessions/join",
    response_model=TableJoinOut,
    summary="Guests enter the order code + PIN they got from staff",
)
async def join_table(slug: Slug, body: TableJoinIn, session: SessionDep, client: ClientDep) -> TableJoinOut:
    tenant = await _public_tenant(session, slug)
    return await svc.join_table(session, tenant, body, client.ip)


@router.get("/table-session", response_model=TableSessionView, summary="My table: orders, times, running total")
async def table_view(session: SessionDep, token: TableToken = None) -> TableSessionView:
    return await svc.table_view(session, token)


@router.post("/table-session/orders", response_model=OrderOut, status_code=201, summary="Order from the table")
async def table_order(
    body: OrderIn,
    response: Response,
    session: SessionDep,
    user: OptionalUser,
    token: TableToken = None,
    idem: IdemKey = None,
) -> OrderOut:
    out, created = await svc.guest_order(session, token, body, idem, user)
    _status(response, created)
    return out


@router.post(
    "/table-session/orders/{order_id}/cancel", response_model=OrderOut, summary="Cancel (only before accepted)"
)
async def table_cancel(order_id: uuid.UUID, session: SessionDep, token: TableToken = None) -> OrderOut:
    return await svc.guest_cancel(session, token, order_id)


@router.post(
    "/me/reservations/{reservation_id}/orders",
    response_model=OrderOut,
    status_code=201,
    summary="Pre-order for a paid booking (free bookings: 403 PREORDER_NOT_ALLOWED)",
)
async def preorder(
    reservation_id: uuid.UUID,
    body: OrderIn,
    response: Response,
    session: SessionDep,
    user: CurrentUser,
    idem: IdemKey = None,
) -> OrderOut:
    out, created = await svc.preorder(session, user, reservation_id, body, idem)
    _status(response, created)
    return out


@router.get("/me/reservations/{reservation_id}/orders", response_model=list[OrderOut], summary="My pre-orders")
async def reservation_orders(reservation_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> list[OrderOut]:
    return await svc.reservation_orders(session, user, reservation_id)


@router.get("/me/orders", response_model=list[OrderOut], summary="My orders (all restaurants)")
async def my_orders(session: SessionDep, user: CurrentUser) -> list[OrderOut]:
    return await svc.my_orders(session, user)


@router.post("/me/orders/{order_id}/cancel", response_model=OrderOut, summary="Cancel my order (only before accepted)")
async def cancel_my_order(order_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> OrderOut:
    return await svc.cancel_mine(session, user, order_id)


# ---------- table QR codes (guests) ----------


class QrStartIn(BaseModel):
    guest_name: str = Field(min_length=1, max_length=60)
    party_size: int = Field(default=2, ge=1, le=40)


class QrJoinIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4}$")


@router.get("/public/restaurants/{slug}/tables/{qr}", summary="Scanned a table QR: which table, free or taken")
async def qr_table(slug: Slug, qr: Annotated[str, Path(min_length=8, max_length=24)], session: SessionDep) -> dict:
    from app.services import table_qr

    return await table_qr.lookup(session, await table_qr.public_tenant(session, slug), qr)


@router.post("/public/restaurants/{slug}/tables/{qr}/start", summary="Start ordering at a free table (self-seating)")
async def qr_start(
    slug: Slug,
    qr: Annotated[str, Path(min_length=8, max_length=24)],
    body: QrStartIn,
    session: SessionDep,
    client: ClientDep,
) -> dict:
    from app.services import table_qr

    tenant = await table_qr.public_tenant(session, slug)
    return await table_qr.start(session, tenant, qr, body.guest_name, body.party_size, client.ip)


@router.post("/public/restaurants/{slug}/tables/{qr}/join", summary="Join an occupied table with its PIN")
async def qr_join(
    slug: Slug,
    qr: Annotated[str, Path(min_length=8, max_length=24)],
    body: QrJoinIn,
    session: SessionDep,
    client: ClientDep,
) -> dict:
    from app.services import table_qr

    tenant = await table_qr.public_tenant(session, slug)
    return await table_qr.join(session, tenant, qr, body.pin, client.ip)
