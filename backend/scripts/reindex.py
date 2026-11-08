"""Re-queue documents whose chunks need (re-)embedding, then let the worker process them.

uv run python -m scripts.reindex          # documents missing embeddings or using an
                                          # embedding model other than EMBED_MODEL
uv run python -m scripts.reindex --all    # every document (e.g. after changing chunking)
"""

import argparse
import asyncio

from sqlalchemy import or_, select, update

from app.config import settings
from app.db import SessionLocal
from app.models import Document, DocumentChunk, DocumentStatus


async def reindex(all_documents: bool) -> None:
    async with SessionLocal() as session:
        query = update(Document).where(Document.status != DocumentStatus.PROCESSING)
        if not all_documents:
            stale = select(DocumentChunk.document_id).where(
                or_(
                    DocumentChunk.embedding.is_(None),
                    DocumentChunk.embedding_model != settings.embed_model,
                )
            )
            query = query.where(Document.id.in_(stale))
        result = await session.execute(query.values(status=DocumentStatus.PENDING, error=None))
        await session.commit()
    print(f"Queued {result.rowcount} document(s). Make sure the worker is running.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-queue documents for processing.")
    parser.add_argument("--all", action="store_true", help="re-queue every document")
    asyncio.run(reindex(parser.parse_args().all))


if __name__ == "__main__":
    main()
