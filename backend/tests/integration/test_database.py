"""Runs against DB_NAME_TEST after `alembic -x test=1 upgrade head`. Skipped if PostgreSQL is unreachable."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_engine, get_sessionmaker, use_system
from app.core.events import record_event

pytestmark = pytest.mark.db


@pytest.fixture(scope="module", autouse=True)
async def _require_db():  # type: ignore[no-untyped-def]
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL test database not reachable: {type(exc).__name__}")


async def test_foundation_tables_exist() -> None:
    async with get_engine().connect() as conn:
        rows = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        tables = {r[0] for r in rows}
    assert {"outbox_events", "idempotency_keys", "audit_logs", "alembic_version"} <= tables


async def test_session_timezone_is_utc() -> None:
    async with get_engine().connect() as conn:
        tz = (await conn.execute(text("SHOW timezone"))).scalar_one()
    assert tz == "UTC"


async def test_uuidv7_default_and_outbox_insert() -> None:
    async with get_sessionmaker()() as session:
        ev = record_event(session, "test.ping", {"n": 1}, room="test")
        await session.flush()
        assert ev.id is not None and ev.id.version == 7
        await session.rollback()


async def test_audit_log_is_append_only() -> None:
    async with get_sessionmaker()() as session:
        await session.execute(text("INSERT INTO audit_logs (action, entity) VALUES ('test', 'test')"))
        # Phase 12: RLS hides platform entries from tenant-less sessions — nothing to update there …
        hidden = await session.execute(text("UPDATE audit_logs SET action = 'changed' WHERE action = 'test'"))
        assert hidden.rowcount == 0
        # … and even the platform (system scope) cannot change history.
        await use_system(session)
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("UPDATE audit_logs SET action = 'changed'"))
        await session.rollback()
