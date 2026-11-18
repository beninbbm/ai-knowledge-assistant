"""Create a user from the command line, optionally as an admin (superuser).

The public /auth/register endpoint can never create admins, so the first admin must be
made here:

    uv run python -m scripts.create_user admin@example.com --admin
"""

import argparse
import asyncio
import getpass

from fastapi_users.exceptions import UserAlreadyExists
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from app.auth.users import UserManager
from app.db import SessionLocal
from app.models import User
from app.schemas import UserCreate


async def create_user(email: str, password: str, admin: bool) -> None:
    async with SessionLocal() as session:
        manager = UserManager(SQLAlchemyUserDatabase(session, User))
        try:
            user = await manager.create(
                UserCreate(email=email, password=password, is_superuser=admin, is_verified=True)
            )
        except UserAlreadyExists:
            print(f"A user with email {email} already exists.")
            return
        print(f"Created {'admin' if admin else 'user'} {user.email} (id {user.id})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("--admin", action="store_true", help="make this user an admin")
    parser.add_argument("--password", help="omit to be prompted (keeps it out of shell history)")
    args = parser.parse_args()
    password = args.password or getpass.getpass("Password: ")
    asyncio.run(create_user(args.email, password, args.admin))


if __name__ == "__main__":
    main()
