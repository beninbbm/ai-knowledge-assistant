"""Ask a question from the terminal, as a given user, and watch the answer stream in.

uv run python -m scripts.ask "How long is parental leave?" --as you@example.com
uv run python -m scripts.ask "..." --as you@example.com --show-prompt   # see what the LLM reads
"""

import argparse
import asyncio
import sys
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.llm.chat import OllamaChat
from app.llm.embeddings import OllamaEmbedder
from app.llm.prompts import build_messages
from app.models import User
from app.rag import DoneEvent, TokenEvent, generate, retrieve


async def run(question: str, email: str, k: int, show_prompt: bool) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            raise SystemExit(f"No user with email {email}")
        started = time.perf_counter()
        sources = await retrieve(session, OllamaEmbedder(), user.id, question, k=k)
    print(f"Retrieved {len(sources)} passages in {time.perf_counter() - started:.1f}s\n")

    if show_prompt:
        for message in build_messages(question, sources):
            print(f"===== {message['role'].upper()} =====\n{message['content']}\n")
        print("===== ANSWER =====")

    started = time.perf_counter()
    first_token = None
    async for event in generate(OllamaChat(), question, sources):
        if isinstance(event, TokenEvent):
            first_token = first_token or time.perf_counter()
            sys.stdout.write(event.text)
            sys.stdout.flush()
        elif isinstance(event, DoneEvent):
            answer = event.answer
    total = time.perf_counter() - started

    print("\n\n--- citations (checked) ---")
    for c in answer.citations:
        page = f", p.{c.page_start}" if c.page_start else ""
        print(f"[{c.number}] {c.document_title}{page} > {' > '.join(c.heading_path[1:])}")
    if not answer.citations:
        print("(none)")
    timing = f"first word after {first_token - started:.1f}s, " if first_token else ""
    usage = answer.usage
    tokens = f", read {usage.prompt_tokens} tokens, wrote {usage.answer_tokens}" if usage else ""
    print(f"\n({timing}done in {total:.1f}s{tokens})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask a question about your documents.")
    parser.add_argument("question")
    parser.add_argument("--as", dest="email", required=True, help="ask as this user")
    parser.add_argument("-k", type=int, default=8, help="passages to retrieve")
    parser.add_argument("--show-prompt", action="store_true", help="print the full prompt")
    args = parser.parse_args()
    asyncio.run(run(args.question, args.email, args.k, args.show_prompt))


if __name__ == "__main__":
    main()
