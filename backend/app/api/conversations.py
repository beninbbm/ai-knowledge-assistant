"""Conversations: multi-turn chat where follow-up questions build on earlier ones."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ask import to_sse
from app.auth.users import CurrentUser
from app.db import SessionDep
from app.llm.chat import ChatError, ChatModel, get_chat_model
from app.llm.embeddings import Embedder, EmbeddingError, get_embedder
from app.models import (
    Conversation,
    Document,
    Message,
    MessageCitation,
    MessageRole,
    User,
)
from app.observability import AnswerTimer, log_answer
from app.permissions import can_read_document
from app.rag import Answer, DoneEvent, generate, retrieve
from app.ratelimit import questions
from app.retrieval.condense import condense_question
from app.schemas import (
    AnswerRead,
    AskRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    ConversationUpdate,
    MessageRead,
    StoredCitationRead,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])

# How many earlier messages (user + assistant) the model sees: the last 3 turns.
HISTORY_MESSAGES = 6
TITLE_LENGTH = 80


async def _get_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


async def owned_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Conversation:
    """Dependency: the conversation, if it belongs to the current user (404 otherwise).

    For the streaming endpoint this MUST run as a dependency: dependencies finish before
    the response starts, so a 404 can still be sent. Once a stream has begun, the status
    code has already gone out and an HTTP error can no longer be returned."""
    return await _get_conversation(session, user, conversation_id)


OwnedConversation = Annotated[Conversation, Depends(owned_conversation)]


async def _messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    return list(
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.position)
        )
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, user: CurrentUser, session: SessionDep
) -> ConversationRead:
    conversation = Conversation(user_id=user.id, title=body.title)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


@router.get("")
async def list_conversations(user: CurrentUser, session: SessionDep) -> list[ConversationRead]:
    conversations = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return [ConversationRead.model_validate(c) for c in conversations]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ConversationDetail:
    conversation = await _get_conversation(session, user, conversation_id)
    messages = await _messages(session, conversation_id)
    citations = (
        await session.scalars(
            select(MessageCitation)
            .where(MessageCitation.message_id.in_([m.id for m in messages]))
            .order_by(MessageCitation.number)
        )
    ).all()

    # Re-check access to every cited document NOW: sharing may have changed since.
    cited_documents = {c.document_id for c in citations if c.document_id}
    readable = set(
        await session.scalars(
            select(Document.id).where(Document.id.in_(cited_documents), can_read_document(user.id))
        )
    )

    by_message: dict[uuid.UUID, list[StoredCitationRead]] = {}
    for c in citations:
        if c.document_id in readable:
            view = StoredCitationRead(
                number=c.number,
                available=True,
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                heading_path=c.heading_path,
                page_start=c.page_start,
                page_end=c.page_end,
                text=c.text,
            )
        else:
            view = StoredCitationRead(number=c.number, available=False)
        by_message.setdefault(c.message_id, []).append(view)

    return ConversationDetail(
        **ConversationRead.model_validate(conversation).model_dump(),
        messages=[
            MessageRead.model_validate(m).model_copy(update={"citations": by_message.get(m.id, [])})
            for m in messages
        ],
    )


@router.patch("/{conversation_id}")
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser, session: SessionDep
) -> ConversationRead:
    conversation = await _get_conversation(session, user, conversation_id)
    conversation.title = body.title.strip()
    await session.commit()
    await session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    conversation = await _get_conversation(session, user, conversation_id)
    await session.delete(conversation)  # messages and citations are deleted by the database
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _save_turn(
    session: AsyncSession,
    conversation: Conversation,
    position: int,
    question: str,
    standalone: str,
    answer: Answer,
) -> tuple[Message, Message]:
    user_message = Message(
        conversation_id=conversation.id,
        position=position,
        role=MessageRole.USER,
        content=question,
        standalone_query=standalone,
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        position=position + 1,
        role=MessageRole.ASSISTANT,
        content=answer.answer,
        model=answer.model,
        prompt_tokens=answer.usage.prompt_tokens if answer.usage else None,
        answer_tokens=answer.usage.answer_tokens if answer.usage else None,
    )
    session.add_all([user_message, assistant_message])
    await session.flush()  # assigns ids so citations can reference the message
    session.add_all(
        MessageCitation(
            message_id=assistant_message.id,
            number=c.number,
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            document_title=c.document_title,
            heading_path=c.heading_path,
            page_start=c.page_start,
            page_end=c.page_end,
            text=c.text,
        )
        for c in answer.citations
    )
    if not conversation.title:
        title = " ".join(question.split())
        conversation.title = (
            title if len(title) <= TITLE_LENGTH else title[: TITLE_LENGTH - 1] + "…"
        )
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    return user_message, assistant_message


@router.post(
    "/{conversation_id}/messages",
    response_class=EventSourceResponse,
    dependencies=[Depends(questions.dependency())],
)
async def send_message(
    conversation: OwnedConversation,
    body: AskRequest,
    user: CurrentUser,
    session: SessionDep,
    embedder: Annotated[Embedder, Depends(get_embedder)],
    chat: Annotated[ChatModel, Depends(get_chat_model)],
) -> AsyncIterator[ServerSentEvent]:
    """Ask the next question in a conversation. Streams Server-Sent Events:

    - `rewritten`: the follow-up rewritten as a standalone search question (if changed)
    - `sources`, `token`: as for /ask/stream
    - `done`: the checked answer plus the ids of the two saved messages
    - `error`: something went wrong; nothing is saved
    """
    earlier = await _messages(session, conversation.id)
    history = [{"role": m.role.value, "content": m.content} for m in earlier[-HISTORY_MESSAGES:]]
    question = body.question.strip()

    try:
        # 1. Make the question searchable on its own ("what about contractors?" ->
        #    "How much parental leave do contractors get?").
        timer = AnswerTimer()
        standalone = await condense_question(chat, history, question)
        timer.mark("rewrite_ms")
        rewritten = standalone if standalone.lower() != question.lower() else None
        if rewritten:
            yield ServerSentEvent(event="rewritten", data={"question": rewritten})

        # 2-4. Retrieve with the standalone question; answer the real one, with history.
        sources = await retrieve(
            session, embedder, user.id, question, body.k, history, search_query=rewritten
        )
        timer.mark("retrieval_ms")
        answering = generate(chat, question, sources, history, interpreted_as=rewritten)
        async for event in timer.track(answering):
            if not isinstance(event, DoneEvent):
                yield to_sse(event)
                continue
            # 5. Save the turn, then report the final answer.
            user_message, assistant_message = await _save_turn(
                session, conversation, len(earlier), question, standalone, event.answer
            )
            log_answer(timer, event.answer, user.id, question, conversation.id, rewritten)
            data = AnswerRead.model_validate(event.answer).model_dump(mode="json")
            data |= {
                "conversation_id": str(conversation.id),
                "user_message_id": str(user_message.id),
                "assistant_message_id": str(assistant_message.id),
                "standalone_question": standalone,
            }
            yield ServerSentEvent(event="done", data=data)
    except (EmbeddingError, ChatError) as exc:
        yield ServerSentEvent(event="error", data={"message": str(exc)})
