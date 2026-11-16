"""Async SQLAlchemy engine/session and tenant (RLS) context.

Row-Level Security policies read two transaction-local settings:
    app.tenant_id   — the tenant this transaction acts for
    app.bypass_rls  — 'on' only for deliberate system/platform operations

Callers never set them by hand: put the context on the session with `use_tenant()` / `use_system()`,
and the `after_begin` listener applies it to every transaction the session opens (including after commit).
"""

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

_TENANT_KEY = "tenant_id"
_BYPASS_KEY = "bypass_rls"


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url(test=s.environment == "test"),
            pool_size=s.db_pool_size,
            pool_pre_ping=True,
            echo=s.db_echo,
            connect_args={"server_settings": {"timezone": "UTC", "application_name": "waitless-api"}},
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request. Services own commit/rollback."""
    async with get_sessionmaker()() as session:
        yield session


# ---------- tenant context ----------


@event.listens_for(Session, "after_begin")
def _apply_context(session: Session, _tx: SessionTransaction, connection: Connection) -> None:
    tenant_id = session.info.get(_TENANT_KEY)
    bypass = session.info.get(_BYPASS_KEY, False)
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tid, true), set_config('app.bypass_rls', :bypass, true)"),
        {"tid": str(tenant_id) if tenant_id else "", "bypass": "on" if bypass else "off"},
    )


async def _reapply_if_in_transaction(session: AsyncSession) -> None:
    if session.in_transaction():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true), set_config('app.bypass_rls', :bypass, true)"),
            {
                "tid": str(session.info.get(_TENANT_KEY) or ""),
                "bypass": "on" if session.info.get(_BYPASS_KEY) else "off",
            },
        )


async def use_tenant(session: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    """Scope this session to one tenant. RLS hides every other tenant's rows."""
    session.info[_TENANT_KEY] = tenant_id
    session.info[_BYPASS_KEY] = False
    await _reapply_if_in_transaction(session)


async def use_system(session: AsyncSession) -> None:
    """Platform-level access (auth lookups, registration, Super Admin). Use deliberately; audit privileged writes."""
    session.info[_TENANT_KEY] = None
    session.info[_BYPASS_KEY] = True
    await _reapply_if_in_transaction(session)


async def ping_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
