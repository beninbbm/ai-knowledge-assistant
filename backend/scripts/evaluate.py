"""Evaluate retrieval and answer quality against the golden questions in eval/questions.yaml.

    uv run python -m scripts.evaluate                    # retrieval + answers with k=8
    uv run python -m scripts.evaluate --k 3 5 8          # compare different passage counts
    uv run python -m scripts.evaluate --retrieval-only   # fast: no LLM answers
    uv run python -m scripts.evaluate --only lb-beats,tr-mileage

It creates a temporary user, uploads every file in samples/ through the real pipeline
(real embeddings), runs each question through the real RAG flow (real LLM), scores the
results, and deletes the user again. A JSON report with every answer is written to
eval/results/ so you can see exactly what went wrong in failed cases.

What's measured
- Retrieval: where the expected passage ranks in search results -> hit@k (is it in the
  top k?) and MRR (mean reciprocal rank: 1 if always first, 0.5 if always second...).
- Answers: facts correct (expected facts appear), cited correctly (a citation points at
  the expected passage), refused correctly (unanswerable questions get "couldn't find"),
  and timing (seconds until the first word, and in total).
"""

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import delete, select

from app.config import REPO_ROOT, settings
from app.db import SessionLocal
from app.ingestion.extractors import detect_file_type
from app.ingestion.pipeline import process_document
from app.llm.chat import OllamaChat
from app.llm.embeddings import OllamaEmbedder
from app.models import Document, DocumentStatus, User
from app.rag import Answer, DoneEvent, TokenEvent, generate, retrieve
from app.retrieval.condense import condense_question
from app.retrieval.search import search
from app.storage import get_storage

QUESTIONS = Path(__file__).resolve().parents[1] / "eval" / "questions.yaml"
RESULTS = Path(__file__).resolve().parents[1] / "eval" / "results"
SAMPLES = REPO_ROOT / "samples"
EVAL_EMAIL = "eval-runner@example.com"
RETRIEVAL_KS = (1, 3, 5, 8)

# Ways a model says the answer isn't in the documents.
REFUSAL = re.compile(
    r"couldn'?t find|could not find|no information|not mentioned|isn'?t mentioned|"
    r"(?:does not|doesn'?t) (?:mention|contain|specify|say)|not (?:specified|provided|included)",
    re.IGNORECASE,
)


@dataclass
class Case:
    id: str
    category: str
    question: str
    document: str | None = None
    headings: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)

    @property
    def answerable(self) -> bool:
        return self.category != "unanswerable"


@dataclass
class AnswerResult:
    id: str
    category: str
    question: str
    rewritten: str | None
    answer: str
    passed: bool
    facts_ok: bool
    cited_ok: bool
    retrieved_ok: bool  # the expected passage was among those given to the model
    refused: bool
    missing_facts: list[str]
    citations: list[str]
    sources: int
    prompt_tokens: int
    first_token_s: float
    total_s: float


def load_cases(only: set[str] | None) -> list[Case]:
    cases = [Case(**raw) for raw in yaml.safe_load(QUESTIONS.read_text())]
    return [c for c in cases if not only or c.id in only]


def _normalise(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'").lower()


def _matches(case: Case, filename: str, heading_path: list[str]) -> bool:
    return filename == case.document and bool(heading_path) and heading_path[-1] in case.headings


# ---------------------------------------------------------------------------
# Setup: a throwaway user with every sample document, processed for real
# ---------------------------------------------------------------------------


async def remove_eval_user() -> None:
    storage = get_storage()
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == EVAL_EMAIL))
        if user is None:
            return
        for path in await session.scalars(
            select(Document.storage_path).where(Document.owner_id == user.id)
        ):
            storage.delete(path)
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


async def setup_library(embedder: OllamaEmbedder) -> tuple[uuid.UUID, dict[uuid.UUID, str]]:
    await remove_eval_user()
    storage = get_storage()
    async with SessionLocal() as session:
        # Inserted directly: this account has no usable password and can't log in.
        user = User(email=EVAL_EMAIL, hashed_password="!", is_active=True)
        session.add(user)
        await session.flush()
        documents = {}
        for path in sorted(SAMPLES.iterdir()):
            data = path.read_bytes()
            file_type = detect_file_type(path.name, data)
            if file_type is None:
                continue
            doc = Document(
                id=uuid.uuid4(),
                owner_id=user.id,
                title=path.stem,
                filename=path.name,
                mime_type=file_type.value,
                sha256=hashlib.sha256(data).hexdigest(),
                storage_path=f"{user.id}/{uuid.uuid4()}{path.suffix}",
                size_bytes=len(data),
                status=DocumentStatus.PROCESSING,
            )
            storage.save(doc.storage_path, data)
            session.add(doc)
            documents[doc.id] = path.name
        await session.commit()
        user_id = user.id

    for doc_id, name in documents.items():
        status = await process_document(SessionLocal, storage, embedder, doc_id)
        if status != DocumentStatus.READY:
            raise SystemExit(f"Could not process {name}; is Ollama running?")
    return user_id, documents


# ---------------------------------------------------------------------------
# Retrieval evaluation (no LLM)
# ---------------------------------------------------------------------------


async def evaluate_retrieval(
    cases: list[Case], embedder: OllamaEmbedder, user_id: uuid.UUID, documents: dict[uuid.UUID, str]
) -> dict:
    """Rank of the expected passage for single-turn answerable questions."""
    ranks: dict[str, int | None] = {}
    for case in cases:
        if not case.answerable or case.history:
            continue  # follow-ups need the LLM rewrite; measured in the answer evaluation
        async with SessionLocal() as session:
            results = await search(session, embedder, user_id, case.question, k=max(RETRIEVAL_KS))
        ranks[case.id] = next(
            (
                i
                for i, r in enumerate(results, 1)
                if _matches(case, documents[r.document_id], r.heading_path)
            ),
            None,
        )
    n = len(ranks)
    summary = {f"hit@{k}": sum(1 for r in ranks.values() if r and r <= k) / n for k in RETRIEVAL_KS}
    summary["mrr"] = sum(1 / r for r in ranks.values() if r) / n
    return {"summary": summary, "ranks": ranks}


# ---------------------------------------------------------------------------
# Answer evaluation (real LLM)
# ---------------------------------------------------------------------------


async def _answer(
    chat: OllamaChat,
    embedder: OllamaEmbedder,
    user_id: uuid.UUID,
    question: str,
    k: int,
    history: list[dict[str, str]],
    rewritten: str | None,
) -> tuple[Answer, list, float, float]:
    started = time.perf_counter()
    first_token = None
    async with SessionLocal() as session:
        sources = await retrieve(
            session, embedder, user_id, question, k, history, search_query=rewritten
        )
    answer = None
    async for event in generate(chat, question, sources, history, interpreted_as=rewritten):
        if isinstance(event, TokenEvent) and first_token is None:
            first_token = time.perf_counter() - started
        elif isinstance(event, DoneEvent):
            answer = event.answer
    total = time.perf_counter() - started
    assert answer is not None
    return answer, sources, first_token or total, total


async def evaluate_case(
    case: Case,
    chat: OllamaChat,
    embedder: OllamaEmbedder,
    user_id: uuid.UUID,
    documents: dict[uuid.UUID, str],
    k: int,
) -> AnswerResult:
    # Play the earlier turns of a follow-up conversation first.
    history: list[dict[str, str]] = []
    for earlier in case.history:
        rewritten_earlier = await condense_question(chat, history, earlier) if history else None
        answer, *_ = await _answer(chat, embedder, user_id, earlier, k, history, rewritten_earlier)
        history += [
            {"role": "user", "content": earlier},
            {"role": "assistant", "content": answer.answer},
        ]

    rewrite_started = time.perf_counter()
    rewritten = None
    if history:
        standalone = await condense_question(chat, history, case.question)
        rewritten = standalone if standalone.lower() != case.question.lower() else None
    rewrite_s = time.perf_counter() - rewrite_started

    answer, sources, first_token_s, total_s = await _answer(
        chat, embedder, user_id, case.question, k, history, rewritten
    )
    text = _normalise(answer.answer)
    refused = bool(REFUSAL.search(text))
    missing = [f for f in case.facts if not re.search(f, text, re.IGNORECASE)]
    retrieved_ok = any(
        _matches(case, documents[s.result.document_id], s.result.heading_path) for s in sources
    )
    cited_ok = any(
        _matches(case, documents[c.document_id], c.heading_path) for c in answer.citations
    )

    # For unanswerable questions the right response is "it isn't in the documents".
    passed = (not missing and cited_ok) if case.answerable else refused
    return AnswerResult(
        id=case.id,
        category=case.category,
        question=case.question,
        rewritten=rewritten,
        answer=answer.answer,
        passed=passed,
        facts_ok=not missing,
        cited_ok=cited_ok,
        retrieved_ok=retrieved_ok,
        refused=refused,
        missing_facts=missing,
        citations=[
            f"[{c.number}] {documents[c.document_id]} > {c.heading_path[-1]}"
            for c in answer.citations
        ],
        sources=answer.sources_considered,
        prompt_tokens=answer.usage.prompt_tokens if answer.usage else 0,
        first_token_s=round(first_token_s + rewrite_s, 2),
        total_s=round(total_s + rewrite_s, 2),
    )


def summarise(results: list[AnswerResult]) -> dict:
    answerable = [r for r in results if r.category != "unanswerable"]
    unanswerable = [r for r in results if r.category == "unanswerable"]

    def share(items, predicate) -> float | None:
        return round(sum(1 for r in items if predicate(r)) / len(items), 3) if items else None

    return {
        "passed": share(results, lambda r: r.passed),
        "facts_correct": share(answerable, lambda r: r.facts_ok),
        "cited_correctly": share(answerable, lambda r: r.cited_ok),
        "passage_retrieved": share(answerable, lambda r: r.retrieved_ok),
        "false_refusals": share(answerable, lambda r: r.refused and not r.facts_ok),
        "correct_refusals": share(unanswerable, lambda r: r.refused),
        "median_first_token_s": round(statistics.median(r.first_token_s for r in results), 2),
        "median_total_s": round(statistics.median(r.total_s for r in results), 2),
        "median_prompt_tokens": round(statistics.median(r.prompt_tokens for r in results)),
        "by_category": {
            category: share([r for r in results if r.category == category], lambda r: r.passed)
            for category in dict.fromkeys(r.category for r in results)
        },
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def pct(value: float | None) -> str:
    return "  -  " if value is None else f"{value * 100:5.1f}%"


def print_case(r: AnswerResult) -> None:
    mark = "PASS" if r.passed else "FAIL"
    detail = ""
    if not r.passed:
        problems = []
        if r.category == "unanswerable":
            problems.append("answered instead of saying it isn't in the documents")
        else:
            if r.missing_facts:
                problems.append(f"missing {r.missing_facts}")
            if not r.cited_ok:
                problems.append(
                    "expected passage not cited" + ("" if r.retrieved_ok else " (not retrieved)")
                )
        detail = "  <- " + "; ".join(problems)
    print(f"  {mark}  {r.id:28} {r.total_s:5.1f}s{detail}")


def print_comparison(runs: dict[int, dict]) -> None:
    ks = list(runs)
    rows = [
        ("Passed overall", "passed", pct),
        ("Facts correct", "facts_correct", pct),
        ("Cited the right passage", "cited_correctly", pct),
        ("Right passage given to model", "passage_retrieved", pct),
        ("False refusals", "false_refusals", pct),
        ("Correct refusals", "correct_refusals", pct),
        ("Median time to first word", "median_first_token_s", lambda v: f"{v:5.1f}s"),
        ("Median total time", "median_total_s", lambda v: f"{v:5.1f}s"),
        ("Median prompt tokens", "median_prompt_tokens", lambda v: f"{v:6d}"),
    ]
    print("\n" + " " * 32 + "".join(f"{'k=' + str(k):>10}" for k in ks))
    for label, key, fmt in rows:
        print(f"  {label:30}" + "".join(f"{fmt(runs[k][key]):>10}" for k in ks))
    categories = list(next(iter(runs.values()))["by_category"])
    print("  Passed by category:")
    for category in categories:
        print(
            f"    {category:28}"
            + "".join(f"{pct(runs[k]['by_category'][category]):>10}" for k in ks)
        )


async def main(args: argparse.Namespace) -> None:
    only = set(args.only.split(",")) if args.only else None
    cases = load_cases(only)
    embedder = OllamaEmbedder()
    chat = OllamaChat(seed=42)  # fixed seed: the same prompt gives the same answer

    print(f"Setting up: processing {len(list(SAMPLES.iterdir()))} sample documents...")
    user_id, documents = await setup_library(embedder)
    report: dict = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "chat_model": settings.chat_model,
            "embed_model": settings.embed_model,
            "chunk_target_tokens": settings.chunk_target_tokens,
            "chunk_overlap_tokens": settings.chunk_overlap_tokens,
            "num_ctx": settings.chat_num_ctx,
        },
    }
    try:
        retrieval = await evaluate_retrieval(cases, embedder, user_id, documents)
        report["retrieval"] = retrieval
        s = retrieval["summary"]
        print(f"\nRETRIEVAL ({len(retrieval['ranks'])} single-turn questions, no LLM)")
        print(
            "  "
            + "  ".join(f"hit@{k} {pct(s[f'hit@{k}'])}" for k in RETRIEVAL_KS)
            + f"  MRR {s['mrr']:.3f}"
        )
        misses = {cid: r for cid, r in retrieval["ranks"].items() if r != 1}
        for cid, rank in misses.items():
            print(
                f"    {cid:28} expected passage ranked {rank or 'below ' + str(max(RETRIEVAL_KS))}"
            )

        if not args.retrieval_only:
            report["answers"] = {}
            summaries = {}
            for k in args.k:
                print(f"\nANSWERS with k={k} ({len(cases)} questions, real LLM)")
                results = []
                for case in cases:
                    result = await evaluate_case(case, chat, embedder, user_id, documents, k)
                    print_case(result)
                    results.append(result)
                summaries[k] = summarise(results)
                report["answers"][str(k)] = {
                    "summary": summaries[k],
                    "results": [asdict(r) for r in results],
                }
            print_comparison(summaries)
    finally:
        await remove_eval_user()

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nFull report (every answer): {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--k", type=int, nargs="+", default=[settings.search_top_k], help="passages per answer"
    )
    parser.add_argument("--retrieval-only", action="store_true", help="skip LLM answers (fast)")
    parser.add_argument("--only", help="comma-separated case ids to run")
    arguments = parser.parse_args()
    try:
        asyncio.run(main(arguments))
    except KeyboardInterrupt:
        asyncio.run(remove_eval_user())
        sys.exit(1)
