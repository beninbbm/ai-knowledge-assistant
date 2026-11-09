"""Shapes of the JSON going in and out of the API (validated by Pydantic)."""

import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.config import settings
from app.models import DocumentStatus


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentRead(ORMModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    error: str | None
    created_at: datetime
    is_owner: bool = False


class ChunkRead(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    token_count: int


class SearchResultRead(ORMModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    chunk_index: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    score: float
    similarity: float | None
    vector_rank: int | None
    keyword_rank: int | None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    k: int = Field(
        default=settings.search_top_k, ge=1, le=20, description="How many passages to retrieve"
    )


class CitationRead(ORMModel):
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    text: str


class UsageRead(ORMModel):
    prompt_tokens: int
    answer_tokens: int


class AnswerRead(ORMModel):
    answer: str
    citations: list[CitationRead]
    sources_considered: int
    model: str | None
    usage: UsageRead | None


class ChunkContextRead(BaseModel):
    """A cited passage plus its neighbours, for reading it in context."""

    document: DocumentRead
    chunk: ChunkRead
    before: list[ChunkRead]
    after: list[ChunkRead]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationRead(ORMModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class StoredCitationRead(BaseModel):
    """A citation saved with an answer. If the user can no longer read the document
    (unshared or deleted), `available` is false and the passage is withheld."""

    number: int
    available: bool
    chunk_id: uuid.UUID | None = None  # None if the chunk was since replaced or deleted
    document_id: uuid.UUID | None = None
    document_title: str | None = None
    heading_path: list[str] = []
    page_start: int | None = None
    page_end: int | None = None
    text: str | None = None


class MessageRead(ORMModel):
    id: uuid.UUID
    position: int
    role: str
    content: str
    standalone_query: str | None
    model: str | None
    created_at: datetime
    citations: list[StoredCitationRead] = []


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]


class DocumentShares(BaseModel):
    """Who a document is shared with (besides its owner). PUT replaces the whole list."""

    user_emails: list[EmailStr] = []
    group_ids: list[uuid.UUID] = []


class GroupCreate(BaseModel):
    name: str


class GroupRead(ORMModel):
    id: uuid.UUID
    name: str
    created_at: datetime


class GroupMemberAdd(BaseModel):
    email: EmailStr


class MemberRead(ORMModel):
    id: uuid.UUID
    email: str
