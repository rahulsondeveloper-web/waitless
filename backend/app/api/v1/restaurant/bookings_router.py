"""Staff side of the walk-in queue and reservations (PRD §12)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, require_feature, require_permission
from app.models import Tenant
from app.schemas.booking import (
    ArriveIn,
    Availability,
    BookingResult,
    PolicyIn,
    PolicyOut,
    QueueEntryOut,
    QueueMoveIn,
    QueueNotifyIn,
    QueueSeatIn,
    ReservationOut,
    StaffQueueIn,
    StaffReservationIn,
)
from app.schemas.tables import SeatedOut
from app.services import queue as queue_svc
from app.services import reservations as res_svc
from app.services import tables as tables_svc
from app.services.access import TenantContext

router = APIRouter(prefix="/restaurant", tags=["restaurant bookings"])

QueuePlan = Depends(require_feature("queue"))
ResPlan = Depends(require_feature("reservations"))
QueueManage = Annotated[TenantContext, Depends(require_permission("queue.manage"))]
ResView = Annotated[TenantContext, Depends(require_permission("reservations.view"))]
ResManage = Annotated[TenantContext, Depends(require_permission("reservations.manage"))]
PolicyManage = Annotated[TenantContext, Depends(require_permission("reservations.policy.manage"))]


# ---------- queue ----------


@router.get("/queue", response_model=list[QueueEntryOut], dependencies=[QueuePlan], summary="Today's queue")
async def list_queue(
    session: SessionDep, ctx: QueueManage, branch_id: uuid.UUID, history: bool = False
) -> list[QueueEntryOut]:
    return await queue_svc.staff_list(session, ctx, branch_id, history)


@router.post("/queue", response_model=QueueEntryOut, status_code=201, dependencies=[QueuePlan], summary="Add walk-in")
async def add_to_queue(body: StaffQueueIn, session: SessionDep, ctx: QueueManage) -> QueueEntryOut:
    return await queue_svc.staff_add(session, ctx, body)


@router.post("/queue/{entry_id}/notify", response_model=QueueEntryOut, dependencies=[QueuePlan], summary="Table ready")
async def notify_queue(
    entry_id: uuid.UUID, body: QueueNotifyIn, session: SessionDep, ctx: QueueManage
) -> QueueEntryOut:
    return await queue_svc.notify(session, ctx, entry_id, body.table_id)


@router.post("/queue/{entry_id}/seat", response_model=SeatedOut, dependencies=[QueuePlan], summary="Seat the guests")
async def seat_queue(entry_id: uuid.UUID, body: QueueSeatIn, session: SessionDep, ctx: QueueManage) -> SeatedOut:
    return await queue_svc.seat(session, ctx, entry_id, body.table_id)


@router.post("/queue/{entry_id}/move", response_model=list[QueueEntryOut], dependencies=[QueuePlan])
async def move_queue(
    entry_id: uuid.UUID, body: QueueMoveIn, session: SessionDep, ctx: QueueManage
) -> list[QueueEntryOut]:
    return await queue_svc.move(session, ctx, entry_id, body.direction)


@router.post("/queue/{entry_id}/skip", response_model=QueueEntryOut, dependencies=[QueuePlan])
async def skip_queue(entry_id: uuid.UUID, session: SessionDep, ctx: QueueManage) -> QueueEntryOut:
    return await queue_svc.end(session, ctx, entry_id, "skipped")


@router.post("/queue/{entry_id}/no-show", response_model=QueueEntryOut, dependencies=[QueuePlan])
async def no_show_queue(entry_id: uuid.UUID, session: SessionDep, ctx: QueueManage) -> QueueEntryOut:
    return await queue_svc.end(session, ctx, entry_id, "no_show")


@router.post("/queue/{entry_id}/cancel", response_model=QueueEntryOut, dependencies=[QueuePlan])
async def cancel_queue(entry_id: uuid.UUID, session: SessionDep, ctx: QueueManage) -> QueueEntryOut:
    return await queue_svc.end(session, ctx, entry_id, "cancelled")


# ---------- reservations ----------


@router.get("/reservations", response_model=list[ReservationOut], dependencies=[ResPlan], summary="Bookings by day")
async def list_reservations(
    session: SessionDep, ctx: ResView, branch_id: uuid.UUID, day: date | None = Query(default=None, alias="date")
) -> list[ReservationOut]:
    return await res_svc.staff_list(session, ctx, branch_id, day)


@router.get(
    "/reservations/availability", response_model=Availability, dependencies=[ResPlan], summary="Slots for staff"
)
async def staff_availability(
    session: SessionDep,
    ctx: ResView,
    branch_id: uuid.UUID,
    day: date = Query(alias="date"),
    party: int = Query(default=2, ge=1, le=50),
) -> Availability:
    branch = await tables_svc._branch(session, ctx, branch_id, "reservations.view")
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    return await res_svc.availability(session, tenant, branch, day, party)


@router.post(
    "/reservations",
    response_model=BookingResult,
    status_code=201,
    dependencies=[ResPlan],
    summary="Phone booking (free)",
)
async def create_reservation(body: StaffReservationIn, session: SessionDep, ctx: ResManage) -> BookingResult:
    return await res_svc.staff_book(session, ctx, body)


@router.post(
    "/reservations/{reservation_id}/arrive",
    response_model=SeatedOut,
    dependencies=[ResPlan],
    summary="Confirm arrival and seat",
)
async def arrive(reservation_id: uuid.UUID, body: ArriveIn, session: SessionDep, ctx: ResManage) -> SeatedOut:
    return await res_svc.arrive(session, ctx, reservation_id, body.table_id)


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationOut, dependencies=[ResPlan])
async def cancel(reservation_id: uuid.UUID, session: SessionDep, ctx: ResManage) -> ReservationOut:
    return await res_svc.staff_cancel(session, ctx, reservation_id)


@router.post("/reservations/{reservation_id}/no-show", response_model=ReservationOut, dependencies=[ResPlan])
async def no_show(reservation_id: uuid.UUID, session: SessionDep, ctx: ResManage) -> ReservationOut:
    return await res_svc.no_show(session, ctx, reservation_id)


@router.get("/branches/{branch_id}/booking-policy", response_model=PolicyOut, summary="Queue & reservation policy")
async def get_policy(branch_id: uuid.UUID, session: SessionDep, ctx: ResView) -> PolicyOut:
    return await res_svc.get_policy(session, ctx, branch_id)


@router.put("/branches/{branch_id}/booking-policy", response_model=PolicyOut, summary="Update the policy")
async def put_policy(branch_id: uuid.UUID, body: PolicyIn, session: SessionDep, ctx: PolicyManage) -> PolicyOut:
    return await res_svc.set_policy(session, ctx, branch_id, body)
