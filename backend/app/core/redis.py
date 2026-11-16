"""Shared Redis (Memurai locally) client + a small distributed lock helper."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis | None:
    """Return the shared client, or None when Redis is disabled (REDIS_URL empty)."""
    global _client
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


@asynccontextmanager
async def redis_lock(name: str, *, ttl_seconds: int = 60) -> AsyncIterator[bool]:
    """Non-blocking lock. Yields True if this process owns the lock, False if another process does.

    Without Redis there is only one process, so the lock is always acquired.
    """
    client = get_redis()
    if client is None:
        yield True
        return
    lock = client.lock(f"lock:{name}", timeout=ttl_seconds, blocking=False)
    acquired = await lock.acquire()
    try:
        yield bool(acquired)
    finally:
        if acquired:
            try:
                await lock.release()
            except Exception:  # lock expired meanwhile — nothing to release
                pass
