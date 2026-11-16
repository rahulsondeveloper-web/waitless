"""Async SQLAlchemy engine/session and tenant context helpers."""

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url(test=s.environment == "test"),
            pool_size=s.db_pool_size,
            pool_pre_ping=True,
            echo=s.db_echo,
            # UTC everywhere (PRD §14, §22)
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


async def set_tenant_context(session: AsyncSession, tenant_id: UUID | None) -> None:
    """Scope the current transaction to a tenant. Read by Row-Level Security policies (Phase 2)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id) if tenant_id else ""},
    )


async def ping_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
