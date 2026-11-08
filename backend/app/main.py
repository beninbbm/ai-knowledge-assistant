"""FastAPI application entry point. Run with: uv run uvicorn app.main:app --reload"""

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import ask, chunks, documents, groups, search
from app.auth.users import auth_backend, fastapi_users
from app.config import settings
from app.db import SessionDep
from app.schemas import UserCreate, UserRead, UserUpdate

app = FastAPI(title="AI Knowledge Assistant")

# Accounts (from fastapi-users): register, log in/out, view/update your own profile.
app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"])
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"]
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"]
)

app.include_router(documents.router)
app.include_router(groups.router)
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(chunks.router)


@app.get("/health")
async def health(session: SessionDep) -> JSONResponse:
    """Reports whether the database, pgvector and Ollama (with both models) are ready."""
    report: dict = {}

    try:
        version = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        report["database"] = {"ok": True, "pgvector": version}
    except Exception as exc:
        report["database"] = {"ok": False, "error": str(exc)}

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            resp.raise_for_status()
        installed = {m["name"] for m in resp.json().get("models", [])}

        def has(model: str) -> bool:
            return model in installed or f"{model}:latest" in installed

        models = {
            settings.chat_model: has(settings.chat_model),
            settings.embed_model: has(settings.embed_model),
        }
        report["ollama"] = {"ok": all(models.values()), "models": models}
    except Exception as exc:
        report["ollama"] = {"ok": False, "error": str(exc)}

    report["ok"] = all(part["ok"] for part in report.values())
    return JSONResponse(report, status_code=200 if report["ok"] else 503)
