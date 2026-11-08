"""Helpers shared by API tests."""

from app.ingestion.pipeline import claim_next_document, process_document


async def upload(client, user, filename: str, data: bytes, **form):
    return await client.post(
        "/documents", files={"file": (filename, data)}, data=form, headers=user.headers
    )


async def run_worker(session_factory, storage, embedder) -> int:
    """Process everything pending, like `python -m app.ingestion.worker --once`."""
    processed = 0
    while True:
        async with session_factory() as session:
            document_id = await claim_next_document(session)
        if document_id is None:
            return processed
        await process_document(session_factory, storage, embedder, document_id)
        processed += 1
