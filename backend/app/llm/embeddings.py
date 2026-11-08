"""Embeddings: turning text into vectors (lists of numbers) that capture its meaning.

Texts with similar meaning get vectors pointing in similar directions, even when they
share no words ("How long can new parents take off?" ~ "16 weeks of parental leave").
We measure that with cosine distance: 0 = same direction, 2 = opposite.

Asymmetric search: nomic-embed-text is trained to embed stored passages and search
queries slightly differently, signalled by a prefix ("search_document: " / "search_query: ").
Forgetting the prefixes noticeably hurts search quality.
"""

from typing import Protocol

import httpx

from app.config import settings


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    model_name: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Calls Ollama's HTTP API: POST /api/embed {"model": ..., "input": [texts]}."""

    def __init__(
        self,
        base_url: str = settings.ollama_url,
        model_name: str = settings.embed_model,
        batch_size: int = settings.embed_batch_size,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url
        self.model_name = model_name
        self.batch_size = batch_size
        self.timeout = timeout

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            for start in range(0, len(inputs), self.batch_size):
                batch = inputs[start : start + self.batch_size]
                try:
                    resp = await client.post(
                        "/api/embed", json={"model": self.model_name, "input": batch}
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise EmbeddingError(
                        f"Could not get embeddings from Ollama at {self.base_url} "
                        f"(model {self.model_name}): {exc}"
                    ) from exc
                vectors.extend(resp.json()["embeddings"])
        for vector in vectors:
            if len(vector) != settings.embed_dimensions:
                raise EmbeddingError(
                    f"Model {self.model_name} returned {len(vector)} dimensions, but the "
                    f"database expects {settings.embed_dimensions}."
                )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed([settings.embed_document_prefix + t for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([settings.embed_query_prefix + text]))[0]


def get_embedder() -> Embedder:
    """FastAPI dependency (tests swap in a fake embedder that needs no Ollama)."""
    return OllamaEmbedder()


def text_for_embedding(document_title: str, heading_path: list[str], text: str) -> str:
    """What we actually embed for a chunk: the text plus where it sits in the document.

    A chunk like "Up to 10 days per year." means little on its own; with
    "Employee Handbook > Leave Policy > Sick Leave" in front, its vector captures what
    it is about. The stored/displayed chunk text stays clean."""
    path = " > ".join(heading_path)
    header = f"Document: {document_title}" + (f"\nSection: {path}" if path else "")
    return f"{header}\n\n{text}"
