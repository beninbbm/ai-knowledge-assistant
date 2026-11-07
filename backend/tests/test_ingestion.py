"""Upload -> worker -> chunks, end to end through the API and the real pipeline."""

import asyncio

import pytest

from app.config import settings
from app.ingestion.pipeline import claim_next_document, process_document
from scripts.make_samples import HANDBOOK, SECURITY, TRAVEL, to_markdown, write_docx, write_pdf


@pytest.fixture
async def alice(make_user):
    return await make_user("alice@example.com")


@pytest.fixture
async def bob(make_user):
    return await make_user("bob@example.com")


@pytest.fixture
def sample_files(tmp_path):
    files = {
        "employee-handbook.md": to_markdown(HANDBOOK).encode(),
    }
    write_docx(SECURITY, tmp_path / "it-security-policy.docx")
    write_pdf(TRAVEL, tmp_path / "travel-expense-policy.pdf")
    for name in ("it-security-policy.docx", "travel-expense-policy.pdf"):
        files[name] = (tmp_path / name).read_bytes()
    return files


async def upload(client, user, filename: str, data: bytes, **form):
    return await client.post(
        "/documents", files={"file": (filename, data)}, data=form, headers=user.headers
    )


async def run_worker(session_factory, storage) -> int:
    """Process everything pending, like `python -m app.ingestion.worker --once`."""
    processed = 0
    while True:
        async with session_factory() as session:
            document_id = await claim_next_document(session)
        if document_id is None:
            return processed
        await process_document(session_factory, storage, document_id)
        processed += 1


async def test_upload_all_formats_and_process(
    client, alice, sample_files, session_factory, storage
):
    ids = {}
    for name, data in sample_files.items():
        resp = await upload(client, alice, name, data)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "pending"  # returned immediately, before processing
        ids[name] = body["id"]

    assert await run_worker(session_factory, storage) == 3

    for name, doc_id in ids.items():
        doc = (await client.get(f"/documents/{doc_id}", headers=alice.headers)).json()
        assert doc["status"] == "ready", (name, doc["error"])
        chunks = (await client.get(f"/documents/{doc_id}/chunks", headers=alice.headers)).json()
        assert chunks, name
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
        assert all(c["heading_path"] for c in chunks)

    pdf_doc = (
        await client.get(f"/documents/{ids['travel-expense-policy.pdf']}", headers=alice.headers)
    ).json()
    assert pdf_doc["page_count"] == 2
    pdf_chunks = (
        await client.get(
            f"/documents/{ids['travel-expense-policy.pdf']}/chunks", headers=alice.headers
        )
    ).json()
    hotels = next(c for c in pdf_chunks if "Hotels" in c["heading_path"][-1])
    assert "$250" in hotels["text"] and hotels["page_start"] == 1


async def test_title_defaults_to_filename(client, alice, sample_files):
    resp = await upload(client, alice, "employee-handbook.md", sample_files["employee-handbook.md"])
    assert resp.json()["title"] == "employee-handbook"
    resp = await upload(client, alice, "other.md", b"# Hi\n\nThere.", title="My notes")
    assert resp.json()["title"] == "My notes"


async def test_rejects_unsupported_and_disguised_files(client, alice):
    assert (await upload(client, alice, "photo.png", b"\x89PNG....")).status_code == 415
    assert (await upload(client, alice, "virus.pdf", b"MZ\x90\x00")).status_code == 415
    assert (await client.get("/documents", headers=alice.headers)).json() == []


async def test_rejects_files_over_the_size_limit(client, alice, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    resp = await upload(client, alice, "big.md", b"x" * 101)
    assert resp.status_code == 413


async def test_duplicate_upload_is_rejected(client, alice, bob):
    first = await upload(client, alice, "a.md", b"# A\n\nSame content.")
    again = await upload(client, alice, "renamed.md", b"# A\n\nSame content.")
    assert again.status_code == 409
    assert again.json()["detail"]["document_id"] == first.json()["id"]
    # A different user may upload the same file; it's their own copy.
    assert (await upload(client, bob, "a.md", b"# A\n\nSame content.")).status_code == 201


async def test_failed_extraction_is_reported(client, alice, session_factory, storage):
    resp = await upload(client, alice, "empty.md", b"# Just a heading\n")
    await run_worker(session_factory, storage)
    doc = (await client.get(f"/documents/{resp.json()['id']}", headers=alice.headers)).json()
    assert doc["status"] == "failed"
    assert "no text" in doc["error"]


async def test_reprocess_requeues_document(client, alice, session_factory, storage):
    doc_id = (await upload(client, alice, "a.md", b"# A\n\nSome text.")).json()["id"]
    await run_worker(session_factory, storage)
    resp = await client.post(f"/documents/{doc_id}/reprocess", headers=alice.headers)
    assert resp.status_code == 202 and resp.json()["status"] == "pending"
    await run_worker(session_factory, storage)
    chunks = (await client.get(f"/documents/{doc_id}/chunks", headers=alice.headers)).json()
    assert len(chunks) == 1  # old chunks replaced, not duplicated


async def test_others_cannot_reach_chunks_or_file(client, alice, bob, session_factory, storage):
    doc_id = (await upload(client, alice, "a.md", b"# Secret\n\nThe launch date is May 3.")).json()[
        "id"
    ]
    await run_worker(session_factory, storage)
    for path in (f"/documents/{doc_id}/chunks", f"/documents/{doc_id}/file"):
        assert (await client.get(path, headers=bob.headers)).status_code == 404
    assert (
        await client.post(f"/documents/{doc_id}/reprocess", headers=bob.headers)
    ).status_code == 404

    await client.put(
        f"/documents/{doc_id}/permissions", json={"user_emails": [bob.email]}, headers=alice.headers
    )
    chunks = await client.get(f"/documents/{doc_id}/chunks", headers=bob.headers)
    assert "May 3" in chunks.json()[0]["text"]
    file = await client.get(f"/documents/{doc_id}/file", headers=bob.headers)
    assert file.status_code == 200 and b"May 3" in file.content
    # Readers can't trigger reprocessing; only the owner can.
    assert (
        await client.post(f"/documents/{doc_id}/reprocess", headers=bob.headers)
    ).status_code == 403


async def test_delete_removes_file_and_chunks(client, alice, session_factory, storage):
    doc_id = (await upload(client, alice, "a.md", b"# A\n\nText.")).json()["id"]
    await run_worker(session_factory, storage)
    stored = list(storage.root.rglob("*.md"))
    assert len(stored) == 1

    assert (await client.delete(f"/documents/{doc_id}", headers=alice.headers)).status_code == 204
    assert not stored[0].exists()
    from sqlalchemy import func, select

    from app.models import DocumentChunk

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(DocumentChunk)) == 0


async def test_two_workers_never_claim_the_same_document(client, alice, session_factory):
    for i in range(4):
        await upload(client, alice, f"doc{i}.md", f"# Doc {i}\n\nText {i}.".encode())

    async def claim():
        async with session_factory() as session:
            return await claim_next_document(session)

    claimed = await asyncio.gather(*(claim() for _ in range(6)))
    real = [c for c in claimed if c is not None]
    assert len(real) == 4 and len(set(real)) == 4
