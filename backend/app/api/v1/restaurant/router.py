"""Restaurant admin (staff) endpoints. Tenant comes from the token + membership, never from the request body."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, TenantCtxAnyStatus, require_permission
from app.core.errors import NotFoundError
from app.models import Branch, Tenant
from app.schemas.tenancy import BranchOut, RestaurantMeOut, TenantOut
from app.services.access import TenantContext, live_subscription, subscription_out

router = APIRouter(prefix="/restaurant", tags=["restaurant"])

BranchesView = Annotated[TenantContext, Depends(require_permission("branches.view"))]


@router.get("/me", response_model=RestaurantMeOut, summary="Active restaurant, its status, plan and branches")
async def restaurant_me(session: SessionDep, ctx: TenantCtxAnyStatus) -> RestaurantMeOut:
    tenant = await session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    stmt = select(Branch).order_by(Branch.is_primary.desc(), Branch.name)
    if not (ctx.all_branches or ctx.permissions.get("branches.view") == "all"):
        stmt = stmt.where(Branch.id.in_(ctx.branch_ids))
    branches = (await session.execute(stmt)).scalars().all()  # RLS: this tenant only
    live = await live_subscription(session, ctx.tenant_id)
    return RestaurantMeOut(
        tenant=TenantOut.model_validate(tenant),
        subscription=subscription_out(*live) if live else None,
        branches=[BranchOut.model_validate(b) for b in branches],
    )


@router.get("/branches", response_model=list[BranchOut], summary="Branches of the active restaurant")
async def list_branches(session: SessionDep, ctx: BranchesView) -> list[BranchOut]:
    rows = (await session.execute(select(Branch).order_by(Branch.is_primary.desc(), Branch.name))).scalars().all()
    return [BranchOut.model_validate(b) for b in rows]


@router.get("/branches/{branch_id}", response_model=BranchOut, summary="One branch")
async def get_branch(branch_id: uuid.UUID, session: SessionDep, ctx: BranchesView) -> BranchOut:
    # No tenant filter in the query on purpose: Row-Level Security alone must hide other tenants' branches.
    branch = (await session.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if branch is None:
        raise NotFoundError("Branch not found.")
    return BranchOut.model_validate(branch)
