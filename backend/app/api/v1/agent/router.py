"""Endpoints for the Floor Agent program on the restaurant's laptop (not for browsers).

`/agent/pair` takes the one-time code from the owner; everything else is signed with the agent key
(`X-Agent-Key`). The key identifies the restaurant and branch: the agent can never name another restaurant.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, field_validator

from app.api.deps import ClientDep, SessionDep
from app.core import rate_limit
from app.models import FloorAgent
from app.services import floor_agent as svc

router = APIRouter(prefix="/agent", tags=["floor agent (camera laptop)"])


async def current_agent(session: SessionDep, x_agent_key: Annotated[str | None, Header(alias="X-Agent-Key")] = None):
    return await svc.agent_from_key(session, x_agent_key)


AgentDep = Annotated[FloorAgent, Depends(current_agent)]


class PairIn(BaseModel):
    code: str = Field(min_length=8, max_length=12)


class EventIn(BaseModel):
    event_id: uuid.UUID  # made by the agent; sending it again (after a lost reply) changes nothing
    kind: Literal["seated", "left"]
    table: str = Field(min_length=1, max_length=20)  # the WaitLess table name, e.g. "T2"
    at: datetime
    guests: int = Field(default=1, ge=1, le=100)

    @field_validator("at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class EventsIn(BaseModel):
    events: list[EventIn] = Field(max_length=svc.MAX_BATCH)


@router.post("/pair", summary="Swap the owner's one-time pairing code for the agent key")
async def pair(body: PairIn, session: SessionDep, client: ClientDep) -> dict:
    await rate_limit.hit(f"agent-pair:{client.ip}", limit=10, window_seconds=600)  # codes are short: slow guessing
    return await svc.pair(session, body.code)


@router.get("/tables", summary="The branch's tables and the waiter in charge of each")
async def tables(session: SessionDep, agent: AgentDep) -> list[dict]:
    return await svc.agent_tables(session, agent)


@router.post("/heartbeat", summary="Still here")
async def heartbeat(agent: AgentDep) -> dict:
    return {"ok": True, "server_time": datetime.now(UTC).isoformat()}


@router.post("/events", summary="Guests seated / guests left at a table")
async def events(body: EventsIn, session: SessionDep, agent: AgentDep) -> dict:
    results = await svc.process_events(session, agent, [e.model_dump() for e in body.events])
    return {"results": results}
