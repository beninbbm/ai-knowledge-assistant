"""Embeddings + hybrid search, including the permission rules."""

import pytest
from sqlalchemy import select

from app.llm.embeddings import OllamaEmbedder, text_for_embedding
from app.models import DocumentChunk
from app.retrieval.fusion import reciprocal_rank_fusion
from scripts.make_samples import HANDBOOK, SECURITY, TRAVEL, to_markdown, write_docx, write_pdf
from tests.helpers import run_worker, upload, upload_samples


@pytest.fixture
async def alice(make_user):
    return await make_user("alice@example.com")


@pytest.fixture
async def bob(make_user):
    return await make_user("bob@example.com")


@pytest.fixture
async def library(client, alice, tmp_path, session_factory, storage, embedder):
    """Alice uploads the three sample documents and the worker processes them."""
    return await upload_samples(client, alice, tmp_path, session_factory, storage, embedder)


async def search(client, user, q: str, k: int = 5) -> list[dict]:
    resp = await client.get("/search", params={"q": q, "k": k}, headers=user.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- building blocks -------------------------------------------------------------------


def test_rrf_rewards_items_found_by_both_methods():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "d"]])
    assert fused[0][0] == "c"  # 3rd in one list + 1st in the other beats 1st in one list
    assert [item for item, _ in fused] == ["c", "a", "b", "d"]
    assert fused[0][1] == pytest.approx(1 / 63 + 1 / 61)


def test_text_for_embedding_adds_context():
    text = text_for_embedding("Handbook", ["Leave Policy", "Sick Leave"], "Up to 10 days.")
    assert text == "Document: Handbook\nSection: Leave Policy > Sick Leave\n\nUp to 10 days."


async def test_chunks_are_stored_with_embeddings(library, session_factory):
    async with session_factory() as session:
        chunks = (await session.scalars(select(DocumentChunk))).all()
    assert chunks
    assert all(c.embedding is not None and len(c.embedding) == 768 for c in chunks)
    assert {c.embedding_model for c in chunks} == {"fake-embedder"}


# --- search results --------------------------------------------------------------------


async def test_finds_the_relevant_passage(client, alice, library):
    results = await search(client, alice, "parental leave for primary caregivers")
    top = results[0]
    assert top["heading_path"][-1] == "Parental Leave"
    assert "16 weeks" in top["text"]
    assert top["document_title"] == "employee-handbook"
    assert top["vector_rank"] == 1 and top["keyword_rank"] is not None


async def test_keyword_search_requires_all_words(client, alice, library, session_factory):
    from app.retrieval.search import keyword_search

    async def headings(query: str) -> list[str]:
        async with session_factory() as session:
            hits = await keyword_search(session, alice.id, query, 20)
            chunks = {c.id: c for c in (await session.scalars(select(DocumentChunk))).all()}
        return [chunks[h].heading_path[-1] for h in hits]

    assert await headings("parking fines") == ["Non-Reimbursable Items"]
    assert await headings("parking ticket") == []  # "ticket" appears nowhere


async def test_keyword_search_catches_exact_terms(client, alice, library):
    results = await search(client, alice, "security@northwind.example")
    assert results[0]["heading_path"][-1] == "Reporting Security Incidents"
    assert results[0]["keyword_rank"] == 1


async def test_results_include_pages_for_pdfs(client, alice, library):
    results = await search(client, alice, "hotel cap per night in major cities")
    top = results[0]
    assert "$250" in top["text"] and top["page_start"] == 1


async def test_k_limits_results(client, alice, library):
    assert len(await search(client, alice, "policy", k=2)) == 2


# --- permissions -----------------------------------------------------------------------


async def test_search_only_returns_readable_documents(client, alice, bob, library):
    query = "parental leave for primary caregivers"
    assert await search(client, bob, query) == []

    handbook = library["employee-handbook.md"]
    await client.put(
        f"/documents/{handbook}/permissions",
        json={"user_emails": [bob.email]},
        headers=alice.headers,
    )
    results = await search(client, bob, query)
    assert results and {r["document_id"] for r in results} == {handbook}

    await client.put(f"/documents/{handbook}/permissions", json={}, headers=alice.headers)
    assert await search(client, bob, query) == []


async def test_documents_that_are_not_ready_are_not_searchable(client, alice, library):
    handbook = library["employee-handbook.md"]
    await client.post(f"/documents/{handbook}/reprocess", headers=alice.headers)  # -> pending
    results = await search(client, alice, "parental leave for primary caregivers")
    assert handbook not in {r["document_id"] for r in results}


async def test_search_requires_login(client):
    assert (await client.get("/search", params={"q": "x"})).status_code == 401


# --- when Ollama is unavailable --------------------------------------------------------


async def test_document_fails_clearly_when_ollama_is_down(client, alice, session_factory, storage):
    unreachable = OllamaEmbedder(base_url="http://127.0.0.1:9", timeout=2)
    doc_id = (await upload(client, alice, "a.md", b"# A\n\nSome text.")).json()["id"]
    await run_worker(session_factory, storage, unreachable)
    doc = (await client.get(f"/documents/{doc_id}", headers=alice.headers)).json()
    assert doc["status"] == "failed"
    assert "Could not get embeddings from Ollama" in doc["error"]


# --- real model (needs Ollama running with nomic-embed-text) ---------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("question", "expected_heading"),
    [
        # Few or no words in common with the passage: mostly meaning connects them.
        ("How long can new mums and dads take off after a baby arrives?", "Parental Leave"),
        ("Can I claim back a parking ticket?", "Non-Reimbursable Items"),
        ("I clicked a dodgy link in an email, what now?", "Reporting Security Incidents"),
    ],
)
async def test_semantic_search_with_real_embeddings(
    client, alice, tmp_path, session_factory, storage, question, expected_heading
):
    real = OllamaEmbedder()
    write_docx(SECURITY, tmp_path / "sec.docx")
    write_pdf(TRAVEL, tmp_path / "travel.pdf")
    await upload(client, alice, "handbook.md", to_markdown(HANDBOOK).encode())
    await upload(client, alice, "sec.docx", (tmp_path / "sec.docx").read_bytes())
    await upload(client, alice, "travel.pdf", (tmp_path / "travel.pdf").read_bytes())
    await run_worker(session_factory, storage, real)

    from app.retrieval.search import search as hybrid_search

    async with session_factory() as session:
        results = await hybrid_search(session, real, alice.id, question, k=3)
    # Retrieval's job is to get the right passage into the top few (all of which go to the
    # LLM), not necessarily first: this is "recall@3".
    headings = [r.heading_path[-1] for r in results]
    assert expected_heading in headings, headings
