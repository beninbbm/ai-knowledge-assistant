"""Show how a file is extracted and chunked, without touching the database.

uv run python -m scripts.inspect_chunks ../samples/travel-expense-policy.pdf
uv run python -m scripts.inspect_chunks FILE --target 200 --overlap 40   # try other sizes
uv run python -m scripts.inspect_chunks FILE --sections                  # raw extraction
uv run python -m scripts.inspect_chunks FILE --full                      # whole chunk text
"""

import argparse
import textwrap
from pathlib import Path

from app.config import settings
from app.ingestion.chunker import chunk_sections
from app.ingestion.extractors import ExtractionError, detect_file_type, extract


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect extraction and chunking of a file.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--target", type=int, default=settings.chunk_target_tokens)
    parser.add_argument("--overlap", type=int, default=settings.chunk_overlap_tokens)
    parser.add_argument("--sections", action="store_true", help="also print extracted sections")
    parser.add_argument("--full", action="store_true", help="print full chunk text")
    args = parser.parse_args()

    file_type = detect_file_type(args.file.name, args.file.read_bytes())
    if file_type is None:
        raise SystemExit(f"Unsupported file type: {args.file.name}")
    try:
        extracted = extract(args.file, file_type.value)
    except ExtractionError as exc:
        raise SystemExit(f"Extraction failed: {exc}") from None

    pages = f", {extracted.page_count} pages" if extracted.page_count else ""
    print(f"{args.file.name}: {file_type.name}{pages}, {len(extracted.sections)} sections\n")

    if args.sections:
        print("=== SECTIONS ===")
        for i, s in enumerate(extracted.sections):
            page = f" p.{s.page}" if s.page else ""
            print(f"[{i}]{page} {' > '.join(s.heading_path) or '(no heading)'}")
            print(textwrap.indent(textwrap.shorten(s.text, 160), "    "))
        print()

    chunks = chunk_sections(extracted.sections, args.target, args.overlap)
    sizes = [c.token_count for c in chunks]
    print(f"=== {len(chunks)} CHUNKS (target {args.target}, overlap {args.overlap} tokens) ===")
    print(f"tokens per chunk: min {min(sizes)}, max {max(sizes)}, avg {sum(sizes) // len(sizes)}\n")
    for i, c in enumerate(chunks):
        if c.page_start is None:
            pages = ""
        elif c.page_start == c.page_end:
            pages = f" | p.{c.page_start}"
        else:
            pages = f" | pp.{c.page_start}-{c.page_end}"
        print(f"--- chunk {i} | ~{c.token_count} tokens{pages} | {' > '.join(c.heading_path)}")
        if args.full:
            print(c.text)
        else:
            print(textwrap.indent(textwrap.shorten(c.text[:400], 200, placeholder=" ..."), "  "))
            if len(c.text) > 400:
                print(f"  ... {textwrap.shorten(c.text[-150:], 120)}")
        print()


if __name__ == "__main__":
    main()
