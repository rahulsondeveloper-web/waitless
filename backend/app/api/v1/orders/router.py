"""Guest ordering (PRD §13): table code + PIN, orders from the table, paid pre-orders, my orders."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Response

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
