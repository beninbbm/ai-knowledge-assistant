"""GET /search: see what retrieval finds for a question, before any LLM is involved."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.users import CurrentUser
from app.db import SessionDep
from app.llm.embeddings import Embedder, EmbeddingError, get_embedder
from app.retrieval.search import search
from app.schemas import SearchResultRead

router = APIRouter(tags=["search"])


@router.get("/search")
async def search_chunks(
    user: CurrentUser,
    session: SessionDep,
    embedder: Annotated[Embedder, Depends(get_embedder)],
    q: Annotated[str, Query(min_length=1, max_length=1000, description="Your question")],
    k: Annotated[int, Query(ge=1, le=50)] = 8,
) -> list[SearchResultRead]:
    try:
        results = await search(session, embedder, user.id, q, k=k)
    except EmbeddingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return [SearchResultRead.model_validate(r) for r in results]
