"""Try retrieval from the terminal, as a given user, and see how each result was found.

uv run python -m scripts.search "how long is parental leave?" --as you@example.com
"""

import argparse
import asyncio
import textwrap

from sqlalchemy import select

from app.db import SessionLocal
from app.llm.embeddings import OllamaEmbedder
from app.models import User
from app.retrieval.search import search


async def run(query: str, email: str, k: int) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            raise SystemExit(f"No user with email {email}")
        results = await search(session, OllamaEmbedder(), user.id, query, k=k)

    print(f'Top {len(results)} results for "{query}" (as {email})\n')
    print("  #  fused  similarity  vector#  keyword#  where")
    for i, r in enumerate(results, start=1):
        similarity = f"{r.similarity:.3f}" if r.similarity is not None else "  -  "
        page = f" p.{r.page_start}" if r.page_start else ""
        where = f"{r.document_title}{page} > {' > '.join(r.heading_path[1:]) or '-'}"
        print(
            f"{i:>3}  {r.score:.4f}  {similarity:>10}  {r.vector_rank or '-':>7}  "
            f"{r.keyword_rank or '-':>8}  {where}"
        )
        print(textwrap.indent(textwrap.shorten(r.text, 150), "       "))


def main() -> None:
    parser = argparse.ArgumentParser(description="Search documents as a user.")
    parser.add_argument("query")
    parser.add_argument("--as", dest="email", required=True, help="search as this user")
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(run(args.query, args.email, args.k))


if __name__ == "__main__":
    main()
