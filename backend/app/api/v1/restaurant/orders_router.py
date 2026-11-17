"""Staff ordering and the kitchen display (PRD §13)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response

from app.api.deps import SessionDep, TenantCtx, require_feature, require_permission
from app.schemas.orders import CancelIn, OrderOut, StaffOrderIn, StatusIn
from app.services import orders as svc
from app.services.access import TenantContext

router = APIRouter(
    prefix="/restaurant", tags=["restaurant orders"], dependencies=[Depends(require_feature("ordering"))]
)

OrdersCreate = Annotated[TenantContext, Depends(require_permission("orders.create"))]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)]


@router.get("/orders", response_model=list[OrderOut], summary="Orders of a branch: active, or all of one day")
async def list_orders(
    session: SessionDep,
    ctx: TenantCtx,
    branch_id: uuid.UUID,
    active: bool = True,
    day: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[OrderOut]:
    return await svc.list_orders(session, ctx, branch_id, active=active, day=day)


@router.post("/orders", response_model=OrderOut, status_code=201, summary="Waiter places an order for a table")
async def staff_order(
    body: StaffOrderIn, response: Response, session: SessionDep, ctx: OrdersCreate, idem: IdemKey = None
) -> OrderOut:
    out, created = await svc.staff_order(session, ctx, body, idem)
    response.status_code = 201 if created else 200
    return out


@router.post("/orders/{order_id}/status", response_model=OrderOut, summary="Accept / preparing / ready / served")
async def set_status(order_id: uuid.UUID, body: StatusIn, session: SessionDep, ctx: TenantCtx) -> OrderOut:
    """Kitchen (`kitchen.operate`) moves orders to ready; only `orders.mark_served` can mark served."""
    return await svc.set_status(session, ctx, order_id, body.status)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut, summary="Cancel an order (with a reason)")
async def cancel(order_id: uuid.UUID, body: CancelIn, session: SessionDep, ctx: TenantCtx) -> OrderOut:
    return await svc.staff_cancel(session, ctx, order_id, body.reason)
