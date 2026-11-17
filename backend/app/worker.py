"""Background worker (decision D27): APScheduler in its own process.

    python -m app.worker

Every job runs under a Redis lock so that running several workers never executes a job twice.
Jobs: heartbeat, reservation_tick, sla_tick. Later phases (outbox dispatch, alerts) register here.
"""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api.v1.health.router import WORKER_HEARTBEAT_KEY
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.logging import setup_logging
from app.core.redis import close_redis, get_redis, redis_lock

log = logging.getLogger("waitless.worker")


Job = Callable[[], Awaitable[None]]


def locked(name: str, ttl_seconds: int = 60) -> Callable[[Job], Job]:
    """Decorator: skip the run if another worker currently holds the job's lock."""

    def wrap(fn: Job) -> Job:
        async def runner() -> None:
            async with redis_lock(f"job:{name}", ttl_seconds=ttl_seconds) as acquired:
                if not acquired:
                    log.debug("job %s skipped (locked elsewhere)", name)
                    return
                await fn()

        runner.__name__ = fn.__name__
        return runner

    return wrap


async def heartbeat() -> None:
    """Lets /api/v1/health report whether the worker is alive."""
    client = get_redis()
    if client is not None:
        await client.set(WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=300)


@locked("reservation_tick", ttl_seconds=55)
async def reservation_tick() -> None:
    """Expire unpaid / no-arrival bookings and mark tables reserved shortly before bookings (PRD §12)."""
    from app.core.db import get_sessionmaker
    from app.services.reservations import tick

    async with get_sessionmaker()() as session:
        counts = await tick(session)
    if any(counts.values()):
        log.info("reservation tick: %s", counts)


@locked("sla_tick", ttl_seconds=14)
async def sla_tick() -> None:
    """Serving timers (PRD §14): at each boundary (15, 20, 25 … min) store the new discount and push it."""
    from app.core.db import get_sessionmaker
    from app.services.orders import _changed
    from app.services.sla import tick

    async with get_sessionmaker()() as session:
        changed = await tick(session)
    for order in changed:
        await _changed(order)
    if changed:
        log.info("sla tick: %d timers advanced", len(changed))


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1})
    scheduler.add_job(heartbeat, "interval", seconds=30, id="heartbeat", next_run_time=datetime.now(UTC))
    scheduler.add_job(reservation_tick, "interval", seconds=60, id="reservation_tick", next_run_time=datetime.now(UTC))
    scheduler.add_job(sla_tick, "interval", seconds=15, id="sla_tick", next_run_time=datetime.now(UTC))
    return scheduler


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    from app.websocket.bus import set_server
    from app.websocket.server import create_emitter

    set_server(create_emitter())  # worker events reach browsers through Redis
    scheduler = build_scheduler()
    scheduler.start()
    log.info("Worker started with jobs: %s", ", ".join(j.id for j in scheduler.get_jobs()))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C arrives as KeyboardInterrupt instead
            pass
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await close_redis()
        await dispose_engine()
        log.info("Worker stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
