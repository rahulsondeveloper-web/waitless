"""Create the dev and test databases if they do not exist yet.

python scripts/create_databases.py
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402


async def main() -> None:
    s = get_settings()
    conn = await asyncpg.connect(
        host=s.db_host,
        port=s.db_port,
        user=s.db_migration_user,
        password=s.db_migration_password or None,
        database="postgres",
    )
    try:
        for name in (s.db_name, s.db_name_test):
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
            if exists:
                print(f"database {name!r} already exists")
            else:
                # Identifiers cannot be bound as parameters; quote safely.
                quoted = '"' + name.replace('"', '""') + '"'
                await conn.execute(f"CREATE DATABASE {quoted} ENCODING 'UTF8' TEMPLATE template0")
                print(f"database {name!r} created")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
