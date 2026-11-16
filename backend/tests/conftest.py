import os

# Must be set before any app module reads settings.
os.environ["ENVIRONMENT"] = "test"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"  # isolated from the dev Redis database

import tempfile  # noqa: E402

# Uploaded files go to a throw-away folder, never backend/uploads.
MEDIA_ROOT = tempfile.mkdtemp(prefix="waitless-test-media-")
os.environ["MEDIA_ROOT"] = MEDIA_ROOT

import random  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine, get_sessionmaker, use_system  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import api  # noqa: E402
from app.models import User  # noqa: E402
from app.seeds.sync import sync_reference_data  # noqa: E402

PASSWORD = "Str0ng-pass!"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=api, client=("203.0.113.10", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def settings():  # type: ignore[no-untyped-def]
    return get_settings()


# ---------- database ----------

_db_ready: bool | None = None


async def _database_available() -> bool:
    global _db_ready
    if _db_ready is None:
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1 FROM tenants LIMIT 1"))
            async with get_sessionmaker()() as session:
                await sync_reference_data(session)
            _db_ready = True
        except Exception:
            _db_ready = False
    return _db_ready


@pytest.fixture(scope="session")
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    """Owner connection (bypasses RLS) used only for test setup/cleanup and RLS assertions."""
    s = get_settings()
    engine = create_async_engine(s.database_url(test=True, migration=True))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(admin_engine: AsyncEngine) -> AsyncIterator[None]:
    """Clean tenant/user data before each DB test. Reference data (permissions, system roles, plans) stays."""
    if not await _database_available():
        pytest.skip("PostgreSQL test database not reachable or not migrated (alembic -x test=1 upgrade head)")
    async with admin_engine.begin() as conn:
        for table in ("tenants", "users", "otp_challenges", "outbox_events", "idempotency_keys"):
            await conn.execute(text(f"DELETE FROM {table}"))
    redis = get_redis()
    if redis is not None:
        await redis.flushdb()
    yield


# ---------- helpers ----------


def random_mobile() -> str:
    return f"9{random.randint(100000000, 999999999)}"


def registration_payload(**overrides: Any) -> dict[str, Any]:
    n = random.randint(1000, 9999)
    data = {
        "restaurant_name": f"Urban Bites {n}",
        "owner_name": "Asha Owner",
        "email": f"owner{n}-{random.randint(0, 99999)}@example.com",
        "mobile": random_mobile(),
        "password": PASSWORD,
        "address": "12 Olive Street, Old Town",
        "city": "Pune",
        "state": "Maharashtra",
        "country": "India",
        "cuisines": ["Italian", "Continental"],
        "restaurant_type": "Casual Dining",
        "number_of_branches": 1,
    }
    data.update(overrides)
    return data


async def register(client: httpx.AsyncClient, **overrides: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = registration_payload(**overrides)
    r = await client.post("/api/v1/public/restaurants/register", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["tenant"], payload


async def login(client: httpx.AsyncClient, identifier: str, password: str = PASSWORD) -> dict[str, Any]:
    r = await client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(auth: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}


def image_bytes(
    width: int = 600, height: int = 400, fmt: str = "PNG", mode: str = "RGB", exif: bytes | None = None
) -> bytes:
    import io

    from PIL import Image

    img = Image.new(mode, (width, height), color=(185, 85, 58) if mode == "RGB" else None)
    out = io.BytesIO()
    kwargs = {"exif": exif} if exif else {}
    img.save(out, fmt, **kwargs)
    return out.getvalue()


async def create_super_admin(email: str = "admin@waitless.test", password: str = PASSWORD) -> None:
    async with get_sessionmaker()() as session:
        await use_system(session)
        session.add(
            User(email=email, full_name="Platform Owner", password_hash=hash_password(password), is_super_admin=True)
        )
        await session.commit()
