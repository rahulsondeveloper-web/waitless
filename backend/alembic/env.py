"""Alembic environment (async). Uses the same settings as the app.

alembic upgrade head                 # dev database (DB_NAME)
alembic -x test=1 upgrade head       # test database (DB_NAME_TEST)
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
use_test_db = context.get_x_argument(as_dictionary=True).get("test") == "1"


def _url():  # type: ignore[no-untyped-def]
    settings = get_settings()
    # Migrations run as the database owner; the app itself runs as the non-owner role (RLS applies).
    return settings.database_url(test=use_test_db or settings.environment == "test", migration=True)


def run_migrations_offline() -> None:
    context.configure(
        url=_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), connect_args={"server_settings": {"timezone": "UTC"}})
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
