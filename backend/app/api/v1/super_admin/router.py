import uuid
from typing import Literal

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from app.api.deps import SessionDep, SuperAdmin
from app.models import Plan
from app.schemas.common import ApiModel, Page
from app.schemas.tenancy import RestaurantAdminRow, RestaurantRegistration, StatusChangeRequest
from app.services import registration, super_admin

router = APIRouter(prefix="/super-admin", tags=["super-admin"])

TenantStatus = Literal["pending", "active", "suspended", "deactivated", "rejected"]


class PlanOut(ApiModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    trial_days: int
    is_active: bool


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/restaurants", response_model=Page[RestaurantAdminRow], summary="All restaurants")
async def list_restaurants(
    session: SessionDep,
    _admin: SuperAdmin,
    status_filter: TenantStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[RestaurantAdminRow]:
    return await super_admin.list_restaurants(session, status=status_filter, q=q, page=page, page_size=page_size)


@router.post(
    "/restaurants",
    response_model=RestaurantAdminRow,
    status_code=status.HTTP_201_CREATED,
    summary="Register a restaurant on behalf of an owner",
)
async def create_restaurant(
    body: RestaurantRegistration, session: SessionDep, admin: SuperAdmin, request: Request
) -> RestaurantAdminRow:
    tenant, _ = await registration.register_restaurant(session, body, actor_user_id=admin.id, ip=_ip(request))
    return await super_admin.get_restaurant(session, tenant.id)


@router.get("/restaurants/{tenant_id}", response_model=RestaurantAdminRow, summary="Restaurant detail")
async def get_restaurant(tenant_id: uuid.UUID, session: SessionDep, _admin: SuperAdmin) -> RestaurantAdminRow:
    return await super_admin.get_restaurant(session, tenant_id)


@router.patch(
    "/restaurants/{tenant_id}/status",
    response_model=RestaurantAdminRow,
    summary="Approve, reject, activate, suspend or deactivate a restaurant",
)
async def change_status(
    tenant_id: uuid.UUID, body: StatusChangeRequest, session: SessionDep, admin: SuperAdmin, request: Request
) -> RestaurantAdminRow:
    return await super_admin.change_status(
        session, tenant_id, body.action, body.reason, actor_user_id=admin.id, ip=_ip(request)
    )


@router.get("/plans", response_model=list[PlanOut], summary="Subscription plans")
async def list_plans(session: SessionDep, _admin: SuperAdmin) -> list[PlanOut]:
    rows = (await session.execute(select(Plan).order_by(Plan.sort_order))).scalars().all()
    return [PlanOut.model_validate(p) for p in rows]
