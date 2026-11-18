"""Guest service: call the waiter, restaurant Wi-Fi, reviews (post-launch additions).

Guests use their table token (no order ID re-entry); staff need tables.operate (waiters, managers, owner)
for calls and restaurant.profile.manage for Wi-Fi and hiding reviews.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query
from pydantic import BaseModel, Field

from app.api.deps import OptionalUser, SessionDep, require_permission
from app.services import guest_service as svc
from app.services.access import TenantContext

router = APIRouter(prefix="/restaurant", tags=["guest service (staff)"])
guest_router = APIRouter(tags=["guest service"])

TablesOperate = Annotated[TenantContext, Depends(require_permission("tables.operate"))]
ProfileManage = Annotated[TenantContext, Depends(require_permission("restaurant.profile.manage"))]
ProfileView = Annotated[TenantContext, Depends(require_permission("restaurant.profile.view"))]
TableToken = Annotated[str | None, Header(alias="X-Table-Token")]


class CallIn(BaseModel):
    kind: Literal["water", "tissue", "bill", "help"]
    guest_name: str = Field(default="", max_length=60)


class WifiIn(BaseModel):
    name: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=64)


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)
    guest_name: str = Field(default="", max_length=60)


class HiddenIn(BaseModel):
    hidden: bool


# ---------- guests ----------


@guest_router.get("/table-session/calls", summary="My table's waiter calls and when I can call again")
async def guest_calls(session: SessionDep, token: TableToken = None) -> dict:
    return await svc.guest_calls(session, token)


@guest_router.post("/table-session/calls", status_code=201, summary="Call the waiter: water, tissue, bill or help")
async def call_waiter(body: CallIn, session: SessionDep, token: TableToken = None) -> dict:
    return await svc.call_waiter(session, token, body.kind, body.guest_name)


@guest_router.get("/table-session/wifi", summary="Restaurant Wi-Fi for guests at a table (null if not set up)")
async def guest_wifi(session: SessionDep, token: TableToken = None) -> dict | None:
    return await svc.guest_wifi(session, token)


@guest_router.get("/table-session/review", summary="Can I review this visit / my review")
async def my_review(session: SessionDep, token: TableToken = None) -> dict:
    return await svc.my_review(session, token)


@guest_router.post("/table-session/review", status_code=201, summary="Rate and review the visit (after paying)")
async def submit_review(body: ReviewIn, session: SessionDep, user: OptionalUser, token: TableToken = None) -> dict:
    return await svc.submit_review(session, token, body.rating, body.comment, body.guest_name, user)


@guest_router.get("/public/restaurants/{slug}/reviews", summary="Public reviews and the average rating")
async def public_reviews(slug: Annotated[str, Path(max_length=60)], session: SessionDep) -> dict:
    return await svc.public_reviews(session, slug)


# ---------- staff ----------


@router.get("/service-calls", summary="Open waiter calls of a branch")
async def open_calls(session: SessionDep, ctx: TablesOperate, branch_id: uuid.UUID = Query()) -> list[dict]:
    return await svc.open_calls(session, ctx, branch_id)


@router.post("/service-calls/{request_id}/done", summary="Reached the table: clear the call")
async def call_done(request_id: uuid.UUID, session: SessionDep, ctx: TablesOperate) -> dict:
    return await svc.call_done(session, ctx, request_id)


@router.get("/guest-wifi", summary="Restaurant Wi-Fi shown to seated guests")
async def get_wifi(session: SessionDep, ctx: ProfileView) -> dict:
    return await svc.get_wifi(session, ctx)


@router.put("/guest-wifi", summary="Set the Wi-Fi name and password for guests")
async def set_wifi(body: WifiIn, session: SessionDep, ctx: ProfileManage) -> dict:
    return await svc.set_wifi(session, ctx, body.name, body.password)


@router.get("/reviews", summary="All reviews (including hidden) and the average rating")
async def staff_reviews(session: SessionDep, ctx: ProfileView) -> dict:
    return await svc.staff_reviews(session, ctx)


@router.patch("/reviews/{review_id}", summary="Hide or show a review on the restaurant page")
async def set_hidden(review_id: uuid.UUID, body: HiddenIn, session: SessionDep, ctx: ProfileManage) -> dict:
    return await svc.set_review_hidden(session, ctx, review_id, body.hidden)
