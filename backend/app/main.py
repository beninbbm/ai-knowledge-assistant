"""FastAPI application entry point. Run with: uv run uvicorn app.main:app --reload"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import ask, chunks, conversations, documents, groups, search
from app.auth.users import auth_backend, fastapi_users
from app.config import settings
from app.db import SessionDep
from app.observability import configure_logging
from app.schemas import UserCreate, UserRead, UserUpdate

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    if settings.jwt_secret in ("", "change-me"):
        log.warning(
            "JWT_SECRET is not set: login tokens use a default, guessable key. Set it in .env."
        )
    yield


app = FastAPI(title="AI Knowledge Assistant", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One line per request: method, path, status and how long it took."""
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path != "/health":
        log.info(
            "%s %s -> %d (%d ms)",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
    return response


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
app.include_router(conversations.router)


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
