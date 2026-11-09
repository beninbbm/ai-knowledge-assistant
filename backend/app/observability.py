"""Logging setup and per-answer metrics.

Each answered question produces one log line like:

    answer user=1f2e… conversation=9a8b… sources=8 cited=2 prompt_tokens=1290
           answer_tokens=41 rewrite_ms=0 retrieval_ms=96 first_token_ms=5230 total_ms=6870

Those numbers are what you'd watch to spot a slow model, a prompt that's too long, or
answers that stop citing sources.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.config import settings
from app.rag import Answer, DoneEvent, SourcesEvent, TokenEvent

log = logging.getLogger("app.answers")


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # httpx logs every request to Ollama at INFO; that's noise next to our own lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass
class AnswerTimer:
    """Stopwatch for one question: call mark() at each step, in milliseconds since start."""

    started: float = field(default_factory=time.perf_counter)
    marks: dict[str, int] = field(default_factory=dict)

    def mark(self, name: str) -> None:
        self.marks[name] = round((time.perf_counter() - self.started) * 1000)

    async def track(
        self, events: AsyncIterator[SourcesEvent | TokenEvent | DoneEvent]
    ) -> AsyncIterator[SourcesEvent | TokenEvent | DoneEvent]:
        """Pass answer events through, noting when the first word and the end arrive."""
        async for event in events:
            if isinstance(event, TokenEvent) and "first_token_ms" not in self.marks:
                self.mark("first_token_ms")
            if isinstance(event, DoneEvent):
                self.mark("total_ms")
            yield event


def log_answer(
    timer: AnswerTimer,
    answer: Answer,
    user_id: uuid.UUID,
    question: str,
    conversation_id: uuid.UUID | None = None,
    rewritten: str | None = None,
) -> None:
    fields: dict[str, object] = {"user": str(user_id)[:8]}
    if conversation_id:
        fields["conversation"] = str(conversation_id)[:8]
    fields |= {
        "sources": answer.sources_considered,
        "cited": len(answer.citations),
        "prompt_tokens": answer.usage.prompt_tokens if answer.usage else 0,
        "answer_tokens": answer.usage.answer_tokens if answer.usage else 0,
        **timer.marks,
    }
    if answer.sources_considered and not answer.citations:
        fields["warning"] = "no_citations"
    if settings.log_question_text:
        fields["question"] = repr(question)
        if rewritten:
            fields["rewritten"] = repr(rewritten)
    log.info("answer %s", " ".join(f"{k}={v}" for k, v in fields.items()))
