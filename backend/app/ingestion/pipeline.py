"""Turn one uploaded document into stored chunks: extract -> chunk -> save.
(Phase 3 adds an "embed" step between chunk and save.)"""

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.ingestion.chunker import TextChunk, chunk_sections
from app.ingestion.extractors import ExtractedDocument, ExtractionError, extract
from app.models import Document, DocumentChunk, DocumentStatus
from app.storage import FileStorage

log = logging.getLogger(__name__)


async def claim_next_document(session: AsyncSession) -> uuid.UUID | None:
    """Take the oldest pending document off the queue and mark it as processing.

    `FOR UPDATE SKIP LOCKED` makes this safe with several workers: each one locks the
    row it picks, and the others skip locked rows instead of waiting or double-claiming.
    """
    document = await session.scalar(
        select(Document)
        .where(Document.status == DocumentStatus.PENDING)
        .order_by(Document.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if document is None:
        await session.rollback()
        return None
    document.status = DocumentStatus.PROCESSING
    document.error = None
    await session.commit()
    return document.id


async def requeue_stale_documents(session: AsyncSession, older_than: timedelta) -> int:
    """Put documents stuck in "processing" (e.g. the worker crashed) back on the queue."""
    result = await session.execute(
        update(Document)
        .where(
            Document.status == DocumentStatus.PROCESSING,
            Document.updated_at < func.now() - older_than,
        )
        .values(status=DocumentStatus.PENDING)
    )
    await session.commit()
    return result.rowcount


def extract_and_chunk(path, mime_type: str) -> tuple[ExtractedDocument, list[TextChunk]]:
    """The CPU-heavy part (no database), also used by scripts/inspect_chunks.py."""
    extracted = extract(path, mime_type)
    chunks = chunk_sections(
        extracted.sections, settings.chunk_target_tokens, settings.chunk_overlap_tokens
    )
    return extracted, chunks


async def process_document(
    session_factory: async_sessionmaker[AsyncSession], storage: FileStorage, document_id: uuid.UUID
) -> DocumentStatus:
    """Extract, chunk and store one claimed document. Records success or failure on it."""
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:  # deleted while queued
            return DocumentStatus.FAILED
        path, mime_type = storage.path(document.storage_path), document.mime_type

    try:
        # Parsing is ordinary blocking code; run it in a thread so the event loop stays free.
        extracted, chunks = await asyncio.to_thread(extract_and_chunk, path, mime_type)
        if not chunks:
            raise ExtractionError("No text could be extracted from this document.")
    except ExtractionError as exc:
        return await _mark_failed(session_factory, document_id, str(exc))
    except Exception as exc:
        log.exception("Unexpected error processing document %s", document_id)
        return await _mark_failed(session_factory, document_id, f"Unexpected error: {exc}")

    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return DocumentStatus.FAILED
        # Replace any chunks from a previous run (e.g. when reprocessing).
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        session.add_all(
            DocumentChunk(
                document_id=document_id,
                chunk_index=i,
                text=c.text,
                heading_path=list(c.heading_path),
                page_start=c.page_start,
                page_end=c.page_end,
                token_count=c.token_count,
            )
            for i, c in enumerate(chunks)
        )
        document.page_count = extracted.page_count
        document.status = DocumentStatus.READY
        document.error = None
        await session.commit()
    log.info("Document %s ready: %d chunks", document_id, len(chunks))
    return DocumentStatus.READY


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID, error: str
) -> DocumentStatus:
    log.warning("Document %s failed: %s", document_id, error)
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.FAILED
            document.error = error
            await session.commit()
    return DocumentStatus.FAILED
