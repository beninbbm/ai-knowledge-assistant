"""ORM table definitions. Tables are added phase by phase."""

import enum
import uuid
from datetime import datetime

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Users and groups
# ---------------------------------------------------------------------------


class User(SQLAlchemyBaseUserTableUUID, TimestampMixin, Base):
    """fastapi-users supplies: id (UUID), email, hashed_password, is_active,
    is_superuser (our "admin" flag) and is_verified."""

    __tablename__ = "users"


class Group(TimestampMixin, Base):
    """A named set of users (e.g. "HR team") that documents can be shared with."""

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


# ---------------------------------------------------------------------------
# Documents and who may read them
# ---------------------------------------------------------------------------


class DocumentStatus(enum.StrEnum):
    """Lifecycle of an upload. "pending" rows are the ingestion worker's to-do list."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        # The same file uploaded twice by the same person is a duplicate.
        UniqueConstraint("owner_id", "sha256", name="uq_documents_owner_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            native_enum=False,
            create_constraint=True,  # CHECK constraint: only these four values
            length=20,
            values_callable=lambda e: [m.value for m in e],
            name="document_status",
        ),
        default=DocumentStatus.PENDING,
        server_default=DocumentStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentPermission(TimestampMixin, Base):
    """Grants read access to one user OR one group (never both, never neither).
    The owner always has access and does not need a row here."""

    __tablename__ = "document_permissions"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, group_id) = 1", name="ck_permission_one_target"),
        Index(
            "uq_permission_doc_user",
            "document_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_permission_doc_group",
            "document_id",
            "group_id",
            unique=True,
            postgresql_where=text("group_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )


class DocumentChunk(Base):
    """A searchable piece of a document (see app/ingestion/chunker.py)."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_doc_index"),
        Index("ix_chunks_document_id", "document_id"),
        # HNSW: an index for fast "nearest vectors" search (approximate, but very close).
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # GIN: an index for fast keyword (full-text) search.
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # order in the document
    text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Semantic search: the chunk's meaning as a vector, and which model produced it
    # (vectors from different models can't be compared, so we track it).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embed_dimensions))
    embedding_model: Mapped[str | None] = mapped_column(String(100))

    # Keyword search: Postgres computes and stores the searchable words ("lexemes") from
    # the text automatically, e.g. "Parental leave policies" -> 'parent' 'leav' 'polici'.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english'::regconfig, text)", persisted=True)
    )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class Conversation(TimestampMixin, Base):
    """A chat thread. Private to the user who started it."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Order within the conversation. (Timestamps can tie: Postgres's now() is the
        # same for every row written in one transaction.)
        UniqueConstraint("conversation_id", "position", name="uq_messages_conversation_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
            name="message_role",
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # User messages: the question rewritten to stand on its own, as used for search.
    standalone_query: Mapped[str | None] = mapped_column(Text)
    # Assistant messages: which model answered and how many tokens it read/wrote.
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    answer_tokens: Mapped[int | None] = mapped_column(Integer)


class MessageCitation(Base):
    """A source cited by an assistant message.

    We keep a copy of the cited passage, because chunks are replaced when a document is
    reprocessed and removed when it's deleted. The copy is only shown while the user can
    still read the document (checked every time the conversation is viewed)."""

    __tablename__ = "message_citations"
    __table_args__ = (
        UniqueConstraint("message_id", "number", name="uq_message_citations_message_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    document_title: Mapped[str] = mapped_column(String(300), nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
