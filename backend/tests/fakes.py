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


class FakeChat:
    """Replies with a scripted answer, streamed word by word, and records every prompt it
    receives, so tests can check exactly what would have been sent to the LLM.

    Query-rewrite requests (follow-up questions) get `rewrite` as the reply, or the
    question unchanged if `rewrite` is None."""

    model_name = "fake-chat"

    def __init__(self, reply: str = "Primary caregivers get 16 weeks [1].") -> None:
        self.reply = reply
        self.rewrite: str | None = None
        self.prompts: list[list[dict[str, str]]] = []  # answer prompts
        self.rewrite_prompts: list[list[dict[str, str]]] = []  # query-rewrite prompts
        self.error: Exception | None = None

    async def stream(self, messages, options=None):
        import re

        from app.llm.chat import ChatChunk, ChatUsage
        from app.retrieval.condense import CONDENSE_SYSTEM_PROMPT

        if self.error:
            raise self.error
        if messages[0]["content"] == CONDENSE_SYSTEM_PROMPT:
            self.rewrite_prompts.append(messages)
            question = re.search(r"Follow-up question: (.*)\n", messages[-1]["content"]).group(1)
            yield ChatChunk(self.rewrite or question, ChatUsage(50, 10))
            return

        self.prompts.append(messages)
        words = self.reply.split(" ")
        for i, word in enumerate(words):
            yield ChatChunk(word if i == 0 else " " + word)
        yield ChatChunk("", ChatUsage(prompt_tokens=100, answer_tokens=len(words)))

    @property
    def last_prompt_text(self) -> str:
        return "\n".join(m["content"] for m in self.prompts[-1])
