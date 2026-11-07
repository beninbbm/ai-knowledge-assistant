"""Authentication: proving who you are."""

from tests.conftest import PASSWORD


async def test_register_login_and_me(client, make_user):
    alice = await make_user("alice@example.com")
    resp = await client.get("/users/me", headers=alice.headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"
    assert resp.json()["is_superuser"] is False


async def test_protected_routes_need_a_login(client):
    assert (await client.get("/documents")).status_code == 401
    assert (await client.get("/groups")).status_code == 401
    assert (await client.get("/users/me")).status_code == 401


async def test_invalid_token_is_rejected(client):
    resp = await client.get("/documents", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


async def test_wrong_password_is_rejected(client, make_user):
    await make_user("alice@example.com")
    resp = await client.post(
        "/auth/jwt/login", data={"username": "alice@example.com", "password": "wrong"}
    )
    assert resp.status_code == 400


async def test_cannot_register_yourself_as_admin(client):
    resp = await client.post(
        "/auth/register",
        json={"email": "sneaky@example.com", "password": PASSWORD, "is_superuser": True},
    )
    assert resp.status_code == 201
    assert resp.json()["is_superuser"] is False


async def test_passwords_are_stored_hashed(client, make_user, session_factory):
    from sqlalchemy import select

    from app.models import User

    await make_user("alice@example.com")
    async with session_factory() as session:
        stored = await session.scalar(select(User.hashed_password))
    assert PASSWORD not in stored
    assert stored.startswith("$argon2")
