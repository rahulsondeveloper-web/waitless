"""Fixed-window rate limiting in Redis. Without Redis (single process) an in-memory counter is used."""

import time
from collections import defaultdict

from fastapi import status

from app.core.errors import AppError
from app.core.redis import get_redis

_memory: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"


async def hit(key: str, *, limit: int, window_seconds: int) -> int:
    """Count one attempt; raise RateLimitedError when the limit is exceeded. Returns the count."""
    client = get_redis()
    if client is None:
        count, started = _memory[key]
        now = time.monotonic()
        if now - started > window_seconds:
            count, started = 0, now
        count += 1
        _memory[key] = (count, started)
        ttl = int(window_seconds - (now - started))
    else:
        rkey = f"rl:{key}"
        pipe = client.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, window_seconds, nx=True)
        pipe.ttl(rkey)
        count, _, ttl = await pipe.execute()
    if count > limit:
        raise RateLimitedError(
            "Too many attempts. Please try again later.",
            details={"retry_after_seconds": max(int(ttl), 1)},
        )
    return int(count)


async def reset(key: str) -> None:
    client = get_redis()
    if client is None:
        _memory.pop(key, None)
    else:
        await client.delete(f"rl:{key}")
