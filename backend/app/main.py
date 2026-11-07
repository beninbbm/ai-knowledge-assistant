"""FastAPI application entry point. Run with: uv run uvicorn app.main:app --reload"""

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.db import SessionDep

app = FastAPI(title="AI Knowledge Assistant")


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
