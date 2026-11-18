import httpx
import pytest

from app.main import app


@pytest.mark.integration
async def test_health_reports_database_and_ollama() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    body = resp.json()
    assert body["database"]["ok"], body
    assert body["database"]["pgvector"]
    assert body["ollama"]["ok"], body
    assert resp.status_code == 200


@pytest.mark.parametrize("secret", ["", "change-me"])
async def test_app_refuses_to_start_with_the_default_jwt_secret(monkeypatch, secret):
    from app.config import settings
    from app.main import app, lifespan

    monkeypatch.setattr(settings, "jwt_secret", secret)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        async with lifespan(app):
            pass
