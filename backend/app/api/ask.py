"""Ask a question and get an answer grounded in your documents, with citations."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.auth.users import CurrentUser
from app.db import SessionDep
from app.llm.chat import ChatError, ChatModel, get_chat_model
from app.llm.embeddings import Embedder, EmbeddingError, get_embedder
from app.observability import AnswerTimer, log_answer
from app.rag import DoneEvent, SourcesEvent, TokenEvent, generate, retrieve
from app.ratelimit import questions
from app.schemas import AnswerRead, AskRequest, CitationRead

router = APIRouter(prefix="/ask", tags=["ask"])

EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
ChatDep = Annotated[ChatModel, Depends(get_chat_model)]


@router.post("", dependencies=[Depends(questions.dependency())])
async def ask(
    body: AskRequest, user: CurrentUser, session: SessionDep, embedder: EmbedderDep, chat: ChatDep
) -> AnswerRead:
    """Wait for the complete answer, then return it in one response."""
    timer = AnswerTimer()
    try:
        sources = await retrieve(session, embedder, user.id, body.question, k=body.k)
        timer.mark("retrieval_ms")
        async for event in timer.track(generate(chat, body.question, sources)):
            if isinstance(event, DoneEvent):
                log_answer(timer, event.answer, user.id, body.question)
                return AnswerRead.model_validate(event.answer)
    except (EmbeddingError, ChatError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No answer produced")


@router.post(
    "/stream",
    response_class=EventSourceResponse,
    dependencies=[Depends(questions.dependency())],
)
async def ask_stream(
    body: AskRequest, user: CurrentUser, session: SessionDep, embedder: EmbedderDep, chat: ChatDep
) -> AsyncIterator[ServerSentEvent]:
    """Stream the answer as Server-Sent Events, so text appears as it's written:

    - `sources`: the passages retrieved (sent first, before the model starts)
    - `token`:   a piece of answer text; append these in order
    - `done`:    the final answer with citations checked (replaces the streamed text)
    - `error`:   something went wrong (e.g. Ollama isn't running)
    """
    timer = AnswerTimer()
    try:
        sources = await retrieve(session, embedder, user.id, body.question, k=body.k)
        timer.mark("retrieval_ms")
        async for event in timer.track(generate(chat, body.question, sources)):
            if isinstance(event, DoneEvent):
                log_answer(timer, event.answer, user.id, body.question)
            yield to_sse(event)
    except (EmbeddingError, ChatError) as exc:
        yield ServerSentEvent(event="error", data={"message": str(exc)})


def to_sse(event: SourcesEvent | TokenEvent | DoneEvent) -> ServerSentEvent:
    """Encode an answering event as a Server-Sent Event."""
    match event:
        case SourcesEvent(sources=found):
            data = [CitationRead.model_validate(c).model_dump(mode="json") for c in found]
            return ServerSentEvent(event="sources", data=data)
        case TokenEvent(text=text):
            return ServerSentEvent(event="token", data={"text": text})
        case DoneEvent(answer=answer):
            data = AnswerRead.model_validate(answer).model_dump(mode="json")
            return ServerSentEvent(event="done", data=data)
