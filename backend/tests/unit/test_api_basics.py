"""Error envelope, request ids and health response shape — no database required."""

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.errors import ConflictError
from app.main import api

# A throwaway router that exercises the error handlers.
_probe = APIRouter(prefix="/__probe")


class _Body(BaseModel):
    qty: int


@_probe.get("/conflict")
async def _conflict() -> None:
    raise ConflictError("Table T5 is already assigned.", code="TABLE_ALREADY_ASSIGNED", details={"table": "T5"})


@_probe.post("/validate")
async def _validate(body: _Body) -> _Body:
    return body


@_probe.get("/boom")
async def _boom() -> None:
    raise RuntimeError("secret internal detail")


api.include_router(_probe)


async def test_app_error_uses_envelope(client: httpx.AsyncClient) -> None:
    r = await client.get("/__probe/conflict")
    assert r.status_code == 409
    assert r.json()["error"] == {
        "code": "TABLE_ALREADY_ASSIGNED",
        "message": "Table T5 is already assigned.",
        "details": {"table": "T5"},
    }


async def test_validation_error_uses_envelope(client: httpx.AsyncClient) -> None:
    r = await client.post("/__probe/validate", json={"qty": "many"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["loc"] == ["body", "qty"]


async def test_unknown_route_is_404_envelope(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


async def test_unhandled_error_hides_details() -> None:
    transport = httpx.ASGITransport(app=api, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__probe/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text


async def test_request_id_is_generated_and_echoed(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/does-not-exist")
    assert len(r.headers["x-request-id"]) == 32
    r2 = await client.get("/api/v1/does-not-exist", headers={"X-Request-ID": "abc-123"})
    assert r2.headers["x-request-id"] == "abc-123"


async def test_health_has_expected_shape(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code in (200, 503)
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert set(body["checks"]) == {"database", "redis", "worker"}
    assert body["server_time"].endswith("Z") or "+00:00" in body["server_time"]


async def test_openapi_is_published(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/health" in r.json()["paths"]
