"""Background worker that processes uploaded documents.

Run it in its own terminal, next to the API server:

    uv run python -m app.ingestion.worker          # keep running, poll for new uploads
    uv run python -m app.ingestion.worker --once   # process everything pending, then exit

The API only *queues* work (a document row with status "pending"); this process does
the slow part so uploads return immediately.
"""

import argparse
import asyncio
import logging
from datetime import timedelta

from app.db import SessionLocal
from app.ingestion.pipeline import claim_next_document, process_document, requeue_stale_documents
from app.llm.embeddings import get_embedder
from app.storage import get_storage

log = logging.getLogger("worker")

POLL_SECONDS = 2.0
STALE_AFTER = timedelta(minutes=10)


async def run(once: bool = False) -> None:
    storage = get_storage()
    embedder = get_embedder()
    async with SessionLocal() as session:
        requeued = await requeue_stale_documents(session, STALE_AFTER)
    if requeued:
        log.info("Re-queued %d stale document(s)", requeued)

    log.info("Worker started; waiting for documents")
    while True:
        async with SessionLocal() as session:
            document_id = await claim_next_document(session)
        if document_id is None:
            if once:
                return
            await asyncio.sleep(POLL_SECONDS)
            continue
        log.info("Processing document %s", document_id)
        await process_document(SessionLocal, storage, embedder, document_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process uploaded documents.")
    parser.add_argument("--once", action="store_true", help="exit when the queue is empty")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(run(once=args.once))
    except KeyboardInterrupt:
        log.info("Worker stopped")


if __name__ == "__main__":
    main()
