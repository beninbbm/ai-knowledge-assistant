"""Database connection: one async engine for the app, and a session per request."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Every ORM table class inherits from this, so Alembic can discover them."""


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: gives each request its own database session."""
    async with SessionLocal() as session:
        yield session


# Use as a route parameter type: `async def route(session: SessionDep): ...`
SessionDep = Annotated[AsyncSession, Depends(get_session)]
