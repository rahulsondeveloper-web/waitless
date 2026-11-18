"""ETag helper for storefront reads and the public storefront socket room."""

from app.api.http_cache import _matches, etag_for
from app.services.storefront_cache import storefront_room
from app.websocket.server import _slug


def test_etag_is_stable_and_weakly_compared() -> None:
    tag = etag_for(b'{"a":1}')
    assert tag == etag_for(b'{"a":1}') and tag != etag_for(b'{"a":2}')
    assert _matches(tag, tag) and _matches(tag.removeprefix("W/"), tag)
    assert _matches(f'"other", {tag}', tag) and _matches("*", tag)
    assert not _matches(None, tag) and not _matches('"other"', tag)


def test_storefront_room_accepts_only_slugs() -> None:
    assert _slug("Urban-Bites") == "urban-bites" and storefront_room("Urban-Bites") == "storefront:urban-bites"
    for bad in (None, "", "a", "x" * 61, "bad slug", "../etc", "t:1:b:2"):
        assert _slug(bad) is None
