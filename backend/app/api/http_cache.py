"""Conditional GET for public storefront reads.

Every response carries an ETag (a hash of its JSON). The browser keeps the response and asks again with
`If-None-Match`; if nothing changed the answer is an empty 304, so unchanged data is never sent twice.
`Cache-Control: no-cache` lets the browser store it but always check — the storefront's own cache
(frontend `HttpCacheService`) decides when to check, and Socket.IO `storefront.changed` tells it when
the restaurant edited something.
"""

import hashlib

from fastapi import Request, Response
from pydantic import BaseModel

CACHE_CONTROL = "no-cache, private"


def etag_for(body: bytes) -> str:
    return 'W/"' + hashlib.sha256(body).hexdigest()[:24] + '"'


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    # weak comparison (RFC 9110 §13.1.2): W/"x" equals "x"
    wanted = etag.removeprefix("W/")
    return any(tag.strip().removeprefix("W/") == wanted for tag in header.split(","))


def etagged(request: Request, model: BaseModel) -> Response:
    body = model.model_dump_json().encode()
    etag = etag_for(body)
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL, "Vary": "Authorization"}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
