"""Shared test setup.

Tests run against the separate `rag_test` database. Tables are created fresh once per
test run and emptied after every test, so each test starts from a clean slate.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import httpx
import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  (register tables)
from app.auth.users import UserManager
from app.config import settings
from app.db import Base, get_session
from app.main import app
from app.models import Document, User
from app.schemas import UserCreate

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.test_database_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(engine, expire_on_commit=False)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client that talks to the app in-process, using the test database."""

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@dataclass
class TestUser:
    id: uuid.UUID
    email: str
    headers: dict[str, str]  # Authorization header with a valid login token

    __test__ = False  # tell pytest this is not a test class


@pytest.fixture
def make_user(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Callable[..., Awaitable[TestUser]]:
    """Create a user (through the real register endpoint, or directly for admins) and log in."""

    async def _make(email: str, admin: bool = False) -> TestUser:
        if admin:
            async with session_factory() as session:
                manager = UserManager(SQLAlchemyUserDatabase(session, User))
                await manager.create(UserCreate(email=email, password=PASSWORD, is_superuser=True))
        else:
            resp = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
            assert resp.status_code == 201, resp.text
        resp = await client.post("/auth/jwt/login", data={"username": email, "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        me = (await client.get("/users/me", headers=headers)).json()
        return TestUser(id=uuid.UUID(me["id"]), email=email, headers=headers)

    return _make


@pytest.fixture
def make_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[uuid.UUID]]:
    """Insert a document row directly (uploading arrives in Phase 2)."""

    async def _make(owner: TestUser, title: str = "Handbook") -> uuid.UUID:
        async with session_factory() as session:
            document = Document(
                owner_id=owner.id,
                title=title,
                filename=f"{title}.pdf",
                mime_type="application/pdf",
                sha256=uuid.uuid4().hex,
                storage_path=f"fake/{title}.pdf",
                size_bytes=1234,
            )
            session.add(document)
            await session.commit()
            return document.id

    return _make
