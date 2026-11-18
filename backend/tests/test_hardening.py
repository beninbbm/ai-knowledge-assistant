"""Rate limits, file-size safety checks and answer logging."""

import io
import logging
import zipfile

import pytest

from app import ratelimit
from app.config import settings
from app.ratelimit import RateLimiter
from tests.helpers import upload, upload_samples


@pytest.fixture
async def alice(make_user):
    return await make_user("alice@example.com")


@pytest.fixture
async def bob(make_user):
    return await make_user("bob@example.com")


def test_sliding_window():
    limiter = RateLimiter("things", limit=2, window_seconds=60)
    assert limiter.hit("u", now=0) is None
    assert limiter.hit("u", now=10) is None
    assert limiter.hit("u", now=20) == pytest.approx(40)  # 3rd within a minute: wait 40s
    assert limiter.hit("other-user", now=20) is None  # limits are per user
    assert limiter.hit("u", now=61) is None  # the first request has left the window


async def test_questions_are_rate_limited_per_user(client, alice, bob, monkeypatch):
    monkeypatch.setattr(ratelimit.questions, "limit", 2)
    for _ in range(2):
        resp = await client.post("/ask", json={"question": "anything?"}, headers=alice.headers)
        assert resp.status_code == 200
    resp = await client.post("/ask/stream", json={"question": "again?"}, headers=alice.headers)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    assert "Too many questions" in resp.json()["detail"]
    # Bob has his own allowance.
    assert (
        await client.post("/ask", json={"question": "hi?"}, headers=bob.headers)
    ).status_code == 200


async def test_conversation_messages_count_as_questions(client, alice, monkeypatch):
    monkeypatch.setattr(ratelimit.questions, "limit", 1)
    conversation = (await client.post("/conversations", json={}, headers=alice.headers)).json()[
        "id"
    ]
    url = f"/conversations/{conversation}/messages"
    assert (
        await client.post(url, json={"question": "one?"}, headers=alice.headers)
    ).status_code == 200
    assert (
        await client.post(url, json={"question": "two?"}, headers=alice.headers)
    ).status_code == 429


async def test_uploads_are_rate_limited(client, alice, monkeypatch):
    monkeypatch.setattr(ratelimit.uploads, "limit", 1)
    assert (await upload(client, alice, "a.md", b"# A\n\nOne.")).status_code == 201
    assert (await upload(client, alice, "b.md", b"# B\n\nTwo.")).status_code == 429


async def test_docx_that_expands_hugely_is_rejected(client, alice, monkeypatch):
    monkeypatch.setattr(settings, "max_docx_uncompressed_bytes", 1_000_000)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "<w:document>" + " " * 5_000_000 + "</w:document>")
    data = buffer.getvalue()
    assert len(data) < 50_000  # tiny on disk...
    resp = await upload(client, alice, "bomb.docx", data)
    assert resp.status_code == 413  # ...but rejected for what it would expand to


async def test_pdf_page_limit(
    client, alice, tmp_path, session_factory, storage, embedder, monkeypatch
):
    from tests.helpers import run_worker

    monkeypatch.setattr(settings, "max_pdf_pages", 1)
    from scripts.make_samples import TRAVEL, write_pdf

    write_pdf(TRAVEL, tmp_path / "travel.pdf")  # 2 pages
    doc_id = (
        await upload(client, alice, "travel.pdf", (tmp_path / "travel.pdf").read_bytes())
    ).json()["id"]
    await run_worker(session_factory, storage, embedder)
    doc = (await client.get(f"/documents/{doc_id}", headers=alice.headers)).json()
    assert doc["status"] == "failed" and "limit is 1" in doc["error"]


async def test_answers_are_logged_without_question_text(
    client, alice, tmp_path, session_factory, storage, embedder, caplog
):
    await upload_samples(client, alice, tmp_path, session_factory, storage, embedder)
    with caplog.at_level(logging.INFO, logger="app.answers"):
        await client.post(
            "/ask", json={"question": "secret parental leave plans?"}, headers=alice.headers
        )
    line = next(r.getMessage() for r in caplog.records if r.name == "app.answers")
    for key in (
        "sources=",
        "cited=",
        "prompt_tokens=",
        "retrieval_ms=",
        "first_token_ms=",
        "total_ms=",
    ):
        assert key in line
    assert "secret" not in line  # question text is off by default
