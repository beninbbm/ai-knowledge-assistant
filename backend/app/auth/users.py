"""Login and accounts, provided by the fastapi-users library.

We only configure it here:
- where users are stored (our `User` table),
- how logins are proven (a signed JWT sent as `Authorization: Bearer <token>`),
- and the `current_active_user` dependency that protects routes.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, InvalidPasswordException, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from app.config import settings
from app.db import SessionDep
from app.models import User

MIN_PASSWORD_LENGTH = 8


async def get_user_db(session: SessionDep) -> AsyncIterator[SQLAlchemyUserDatabase]:
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Handles registration and password checks. Passwords are hashed with Argon2."""

    # Signing secrets for password-reset / email-verification tokens (not used yet).
    reset_password_token_secret = settings.jwt_secret
    verification_token_secret = settings.jwt_secret

    async def validate_password(self, password: str, user) -> None:
        """fastapi-users accepts any password by default; require a sensible minimum."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidPasswordException(
                reason=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        if user.email and user.email.lower() in password.lower():
            raise InvalidPasswordException(reason="Password must not contain your email address.")


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase, Depends(get_user_db)],
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=settings.jwt_secret, lifetime_seconds=settings.jwt_lifetime_seconds)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=BearerTransport(tokenUrl="auth/jwt/login"),
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# Route dependencies: `user: CurrentUser` rejects requests without a valid login (401);
# `admin: CurrentSuperuser` additionally requires is_superuser (403 otherwise).
current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
CurrentUser = Annotated[User, Depends(current_active_user)]
CurrentSuperuser = Annotated[User, Depends(current_superuser)]
