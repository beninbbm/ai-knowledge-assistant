"""Retrieval-Augmented Generation: the full question-answering flow in one place.

question
  -> retrieve: hybrid search over chunks the user may read      (app/retrieval)
  -> augment:  number the best passages and put them in a prompt (app/llm/prompts)
  -> generate: stream the LLM's answer token by token           (app/llm/chat)
  -> verify:   keep only citations that match real sources      (app/llm/citations)
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.chat import ChatModel, ChatUsage
from app.llm.citations import extract_citations
from app.llm.embeddings import Embedder
from app.llm.prompts import NumberedSource, build_messages, fit_sources
from app.retrieval.search import search

NO_SOURCES_ANSWER = "I couldn't find anything about that in the documents you have access to."


@dataclass
class Citation:
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    text: str


@dataclass
class Answer:
    answer: str
    citations: list[Citation]  # only the sources the answer actually cites
    sources_considered: int  # how many passages the model was given
    model: str | None = None
    usage: ChatUsage | None = None


# Events emitted while answering (sent to the browser as Server-Sent Events).
@dataclass
class SourcesEvent:
    sources: list[Citation]  # everything retrieved, before the model starts writing


@dataclass
class TokenEvent:
    text: str


@dataclass
class DoneEvent:
    answer: Answer


def _citation(source: NumberedSource) -> Citation:
    r = source.result
    return Citation(
        number=source.number,
        chunk_id=r.chunk_id,
        document_id=r.document_id,
        document_title=r.document_title,
        heading_path=r.heading_path,
        page_start=r.page_start,
        page_end=r.page_end,
        text=r.text,
    )


async def retrieve(
    session: AsyncSession,
    embedder: Embedder,
    user_id: uuid.UUID,
    question: str,
    k: int = settings.search_top_k,
    history: list[dict[str, str]] | None = None,
    search_query: str | None = None,
) -> list[NumberedSource]:
    """Search (permission-filtered) and keep the results that fit in the prompt.
    `search_query` is the standalone version of a follow-up question, if any."""
    results = await search(session, embedder, user_id, search_query or question, k=k)
    return fit_sources(question, results, history, interpreted_as=search_query)


async def generate(
    chat: ChatModel,
    question: str,
    sources: list[NumberedSource],
    history: list[dict[str, str]] | None = None,
    interpreted_as: str | None = None,
) -> AsyncIterator[SourcesEvent | TokenEvent | DoneEvent]:
    """Stream an answer to `question` grounded in `sources`, continuing `history`."""
    yield SourcesEvent([_citation(s) for s in sources])

    if not sources:
        # Nothing relevant (or nothing the user may read): don't let the model improvise.
        yield TokenEvent(NO_SOURCES_ANSWER)
        yield DoneEvent(Answer(NO_SOURCES_ANSWER, [], 0))
        return

    raw = ""
    usage: ChatUsage | None = None
    messages = build_messages(question, sources, history, interpreted_as)
    async for chunk in chat.stream(messages):
        if chunk.text:
            raw += chunk.text
            yield TokenEvent(chunk.text)
        usage = chunk.usage or usage

    answer, cited = extract_citations(raw, len(sources))
    by_number = {s.number: s for s in sources}
    yield DoneEvent(
        Answer(
            answer=answer,
            citations=[_citation(by_number[n]) for n in sorted(cited)],
            sources_considered=len(sources),
            model=chat.model_name,
            usage=usage,
        )
    )
