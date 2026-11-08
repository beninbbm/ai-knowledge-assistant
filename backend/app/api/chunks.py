"""View a cited passage in context (the source viewer)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.documents import to_read
from app.auth.users import CurrentUser
from app.db import SessionDep
from app.models import DocumentChunk
from app.permissions import get_readable_document
from app.schemas import ChunkContextRead, ChunkRead

router = APIRouter(prefix="/chunks", tags=["sources"])


@router.get("/{chunk_id}")
async def get_chunk(
    chunk_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    context: Annotated[int, Query(ge=0, le=5, description="Neighbouring chunks each side")] = 1,
) -> ChunkContextRead:
    chunk = await session.get(DocumentChunk, chunk_id)
    if chunk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Passage not found")
    # Permission is checked on the chunk's document, every time it's viewed: if access
    # was revoked since the answer was given, the passage is no longer shown.
    try:
        document = await get_readable_document(session, user, chunk.document_id)
    except HTTPException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Passage not found") from None

    neighbours = (
        await session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == chunk.document_id,
                DocumentChunk.chunk_index.between(
                    chunk.chunk_index - context, chunk.chunk_index + context
                ),
                DocumentChunk.id != chunk.id,
            )
            .order_by(DocumentChunk.chunk_index)
        )
    ).all()
    return ChunkContextRead(
        document=to_read(document, user),
        chunk=ChunkRead.model_validate(chunk),
        before=[
            ChunkRead.model_validate(c) for c in neighbours if c.chunk_index < chunk.chunk_index
        ],
        after=[
            ChunkRead.model_validate(c) for c in neighbours if c.chunk_index > chunk.chunk_index
        ],
    )
