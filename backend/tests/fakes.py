"""Test doubles that stand in for Ollama."""

import hashlib
import math
import re

from app.config import settings

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "with",
}


class FakeEmbedder:
    """Deterministic "bag of words" embeddings: each word switches on a few positions in
    the vector, so texts sharing words point in similar directions. No real
    understanding of meaning, but enough to test ranking and permissions offline."""

    model_name = "fake-embedder"

    def __init__(self) -> None:
        self.calls = 0

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * settings.embed_dimensions
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if word in _STOPWORDS:
                continue
            word = word[:5]  # crude stemming: "caregivers" ~ "caregiver"
            digest = hashlib.sha256(word.encode()).digest()
            for i in range(3):
                vector[int.from_bytes(digest[i * 4 : i * 4 + 4]) % len(vector)] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return self._vector(text)
