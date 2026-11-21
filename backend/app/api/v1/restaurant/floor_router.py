"""Floor Agent, owner and waiter side: pair a camera laptop, and the alerts a waiter gets from it.

Pairing needs `tables.configure` (owner, manager). Alerts need `tables.operate` (waiters, managers, owner); a
waiter only sees alerts addressed to them or to the whole branch.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, require_permission
from app.services import floor_agent as svc
from app.services.access import TenantContext

router = APIRouter(prefix="/restaurant", tags=["floor agent (staff)"])

TablesConfigure = Annotated[TenantContext, Depends(require_permission("tables.configure"))]
TablesOperate = Annotated[TenantContext, Depends(require_permission("tables.operate"))]


class AgentCreate(BaseModel):
    branch_id: uuid.UUID
    name: str = Field(default="Floor agent", max_length=60)


@router.post("/floor-agents", status_code=201, summary="Add a camera laptop: returns a one-time pairing code")
async def create_agent(body: AgentCreate, session: SessionDep, ctx: TablesConfigure) -> dict:
    return await svc.create_agent(session, ctx, body.branch_id, body.name)


@router.get("/floor-agents", summary="Camera laptops of a branch and whether they are online")
async def list_agents(session: SessionDep, ctx: TablesConfigure, branch_id: uuid.UUID = Query()) -> list[dict]:
    return await svc.list_agents(session, ctx, branch_id)


@router.delete("/floor-agents/{agent_id}", status_code=204, summary="Disconnect a camera laptop")
async def revoke_agent(agent_id: Annotated[uuid.UUID, Path()], session: SessionDep, ctx: TablesConfigure) -> Response:
    await svc.revoke_agent(session, ctx, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/floor-alerts", summary="My open camera alerts (addressed to me or to the whole branch)")
async def my_alerts(session: SessionDep, ctx: TablesOperate, branch_id: uuid.UUID = Query()) -> list[dict]:
    return await svc.my_alerts(session, ctx, branch_id)


@router.post("/floor-alerts/{alert_id}/ack", summary="Seen it: clear the alert")
async def ack_alert(alert_id: Annotated[uuid.UUID, Path()], session: SessionDep, ctx: TablesOperate) -> dict:
    return await svc.ack_alert(session, ctx, alert_id)
