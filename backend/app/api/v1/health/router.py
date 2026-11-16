import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.db import ping_database
from app.core.redis import get_redis

router = APIRouter(tags=["health"])

WORKER_HEARTBEAT_KEY = "worker:heartbeat"
WORKER_STALE_AFTER_S = 90


class Check(BaseModel):
    status: Literal["ok", "down", "disabled"]
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    server_time: datetime
    checks: dict[str, Check]


async def _timed(coro) -> Check:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    try:
        await coro
        return Check(status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 1))
    except Exception as exc:  # report, never raise, from a health check
        return Check(status="down", detail=type(exc).__name__)


async def _worker_check() -> Check:
    client = get_redis()
    if client is None:
        return Check(status="disabled", detail="Redis disabled; worker heartbeat unavailable")
    try:
        beat = await client.get(WORKER_HEARTBEAT_KEY)
    except Exception as exc:
        return Check(status="down", detail=type(exc).__name__)
    if not beat:
        return Check(status="down", detail="No heartbeat. Is `python -m app.worker` running?")
    age = (datetime.now(UTC) - datetime.fromisoformat(beat)).total_seconds()
    if age > WORKER_STALE_AFTER_S:
        return Check(status="down", detail=f"Last heartbeat {int(age)} s ago")
    return Check(status="ok", detail=f"Last heartbeat {int(age)} s ago")


@router.get("/health", response_model=HealthResponse, summary="Liveness and dependency status")
async def health(response: Response) -> HealthResponse:
    settings = get_settings()
    client = get_redis()
    checks = {
        "database": await _timed(ping_database()),
        "redis": await _timed(client.ping()) if client else Check(status="disabled"),
        "worker": await _worker_check(),
    }
    # Database and Redis are required; the worker being down degrades background jobs only.
    healthy = checks["database"].status == "ok" and checks["redis"].status in ("ok", "disabled")
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        server_time=datetime.now(UTC),
        checks=checks,
    )
