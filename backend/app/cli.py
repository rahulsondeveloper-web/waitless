"""Admin commands.

python -m app.cli seed
python -m app.cli create-super-admin --email you@example.com --name "Your Name" [--phone 98xxxxxxxx]
    (prompts for the password; or set WAITLESS_SUPER_ADMIN_PASSWORD for non-interactive use)
"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.core.db import dispose_engine, get_sessionmaker, use_system
from app.core.phone import normalize_phone
from app.core.security import hash_password
from app.models import User
from app.seeds.sync import sync_reference_data
from app.services.audit import write_audit


async def _seed() -> None:
    async with get_sessionmaker()() as session:
        result = await sync_reference_data(session)
    print(f"Reference data synced: {result}")


async def _create_super_admin(email: str, name: str, phone: str | None, password: str) -> None:
    async with get_sessionmaker()() as session:
        await use_system(session)
        email = email.strip().lower()
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(email=email, full_name=name, phone=phone)
            session.add(user)
            action = "created"
        else:
            action = "promoted"
            if phone:
                user.phone = phone
            user.full_name = name or user.full_name
        user.password_hash = hash_password(password)
        user.is_super_admin = True
        user.is_active = True
        await session.flush()
        write_audit(session, action=f"super_admin.{action}", entity="user", entity_id=user.id, actor_user_id=user.id)
        await session.commit()
    print(f"Super Admin {action}: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Sync permissions, system roles and default plans")
    sa = sub.add_parser("create-super-admin", help="Create or promote the WaitLess Super Admin")
    sa.add_argument("--email", required=True)
    sa.add_argument("--name", required=True)
    sa.add_argument("--phone")
    args = parser.parse_args()

    async def run() -> None:
        try:
            if args.command == "seed":
                await _seed()
            else:
                phone = normalize_phone(args.phone) if args.phone else None
                password = os.environ.get("WAITLESS_SUPER_ADMIN_PASSWORD") or getpass.getpass("Password: ")
                if len(password) < 8:
                    sys.exit("Password must be at least 8 characters.")
                await _create_super_admin(args.email, args.name, phone, password)
        finally:
            await dispose_engine()

    asyncio.run(run())


if __name__ == "__main__":
    main()
