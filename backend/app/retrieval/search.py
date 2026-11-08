"""Hybrid search over the chunks a user is allowed to read.

1. Vector search: embed the question, find chunks whose vectors are closest in meaning.
2. Keyword search: Postgres full-text search for chunks containing the question's words
   (catches exact terms like names, codes and numbers that embeddings can blur).
3. Fuse both ranked lists with Reciprocal Rank Fusion and keep the top k.

Both searches apply the permission filter INSIDE the SQL query, so chunks from documents
the user can't read are never even candidates.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.embeddings import Embedder
from app.models import Document, DocumentChunk, DocumentStatus
from app.permissions import can_read_document
from app.retrieval.fusion import reciprocal_rank_fusion


@dataclass
class SearchResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    chunk_index: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    score: float  # fused RRF score (higher is better)
    similarity: float | None  # cosine similarity to the question, -1..1 (higher is closer)
    vector_rank: int | None  # position in the vector results (None = not found there)
    keyword_rank: int | None  # position in the keyword results


def _searchable_chunks(user_id: uuid.UUID):
    """Chunks of READY documents this user may read."""
    return (
        select(DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.status == DocumentStatus.READY, can_read_document(user_id))
    )


async def vector_search(
    session: AsyncSession, user_id: uuid.UUID, query_vector: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    """(chunk id, cosine distance) of the closest chunks, closest first."""
    # With a filter, the HNSW index may run out of matches before finding `limit` rows.
    # Iterative scanning (pgvector 0.8+) makes it keep searching until it has enough.
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    rows = await session.execute(
        _searchable_chunks(user_id)
        .add_columns(distance.label("distance"))
        .where(DocumentChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    # relaxed_order can return results slightly out of order; sort them exactly.
    return sorted(((row.id, row.distance) for row in rows), key=lambda r: r[1])


async def keyword_search(
    session: AsyncSession, user_id: uuid.UUID, query: str, limit: int
) -> list[uuid.UUID]:
    """Chunk ids containing ALL of the query's words (stemmed, stop words ignored), best
    first.

    Keyword search is the precision tool in hybrid search: it shines on exact terms
    (emails, codes, names, "minimum password length") and simply finds nothing for loose
    natural questions, which vector search handles. We tried matching ANY word instead;
    single common words ("take", "new") then produced weak matches that RRF ranked as
    highly as strong ones, pushing the right answer down.

    websearch_to_tsquery also understands "quoted phrases", OR and -excluded words."""
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(DocumentChunk.tsv, tsquery)
    rows = await session.scalars(
        _searchable_chunks(user_id)
        .where(DocumentChunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc(), DocumentChunk.id)
        .limit(limit)
    )
    return list(rows)


async def search(
    session: AsyncSession,
    embedder: Embedder,
    user_id: uuid.UUID,
    query: str,
    k: int = settings.search_top_k,
    candidates: int = settings.search_candidates,
) -> list[SearchResult]:
    query_vector = await embedder.embed_query(query)
    vector_hits = await vector_search(session, user_id, query_vector, candidates)
    keyword_hits = await keyword_search(session, user_id, query, candidates)

    vector_ids = [chunk_id for chunk_id, _ in vector_hits]
    fused = reciprocal_rank_fusion([vector_ids, keyword_hits])[:k]
    if not fused:
        return []

    distances = dict(vector_hits)
    vector_rank = {chunk_id: i for i, chunk_id in enumerate(vector_ids, start=1)}
    keyword_rank = {chunk_id: i for i, chunk_id in enumerate(keyword_hits, start=1)}

    rows = await session.execute(
        select(DocumentChunk, Document.title)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id.in_([chunk_id for chunk_id, _ in fused]))
    )
    by_id = {chunk.id: (chunk, title) for chunk, title in rows}

    results = []
    for chunk_id, score in fused:
        chunk, title = by_id[chunk_id]
        distance = distances.get(chunk_id)
        results.append(
            SearchResult(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=title,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=score,
                similarity=None if distance is None else 1 - distance,
                vector_rank=vector_rank.get(chunk_id),
                keyword_rank=keyword_rank.get(chunk_id),
            )
        )
    return results
