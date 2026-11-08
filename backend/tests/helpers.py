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


async def upload_samples(client, user, tmp_path, session_factory, storage, embedder) -> dict:
    """Upload the three sample documents as `user` and process them. Returns
    {filename: document id}."""
    from scripts.make_samples import HANDBOOK, SECURITY, TRAVEL, to_markdown, write_docx, write_pdf

    write_docx(SECURITY, tmp_path / "it-security-policy.docx")
    write_pdf(TRAVEL, tmp_path / "travel-expense-policy.pdf")
    files = {
        "employee-handbook.md": to_markdown(HANDBOOK).encode(),
        "it-security-policy.docx": (tmp_path / "it-security-policy.docx").read_bytes(),
        "travel-expense-policy.pdf": (tmp_path / "travel-expense-policy.pdf").read_bytes(),
    }
    ids = {}
    for name, data in files.items():
        ids[name] = (await upload(client, user, name, data)).json()["id"]
    await run_worker(session_factory, storage, embedder)
    return ids


def parse_sse(body: str) -> list[tuple[str, object]]:
    """Split a text/event-stream body into (event name, decoded JSON data) pairs."""
    import json

    events = []
    for block in body.strip().split("\n\n"):
        name, data = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events
