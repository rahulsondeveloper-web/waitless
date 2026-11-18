"""Short-lived Redis cache for public storefront reads (decision D44).

Invalidated on every write that changes what guests see, so edits and suspensions are immediate.
Cache failures never break a request.
"""

from app.core.config import get_settings
from app.core.redis import get_redis

PARTS = ("", ":gallery", ":menu")


def cache_key(slug: str, part: str = "") -> str:
    return f"storefront:{slug.lower()}{part}"


def storefront_room(slug: str) -> str:
    """Socket.IO room of everyone viewing a restaurant's public pages (no sign-in needed)."""
    return f"storefront:{slug.lower()}"


async def invalidate_storefront(slug: str) -> None:
    client = get_redis()
    if client is not None:
        try:
            await client.delete(*(cache_key(slug, p) for p in PARTS))
        except Exception:
            pass
    # Open storefront pages drop their browser cache and fetch again (HttpCacheService in the frontend).
    from app.websocket.bus import emit

    await emit("storefront.changed", {"slug": slug.lower()}, storefront_room(slug))


async def cache_get(key: str) -> str | None:
    client = get_redis()
    if client is None:
        return None
    try:
        return await client.get(key)
    except Exception:
        return None


async def cache_set(key: str, value: str) -> None:
    client = get_redis()
    if client is not None:
        try:
            await client.set(key, value, ex=get_settings().storefront_cache_seconds)
        except Exception:
            pass
