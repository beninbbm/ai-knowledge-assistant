"""PDF text extraction with PyMuPDF.

PDFs have no real notion of paragraphs or headings: they are just positioned text on
pages. So we reconstruct structure:

- Paragraphs: PyMuPDF groups nearby lines into *blocks*, which are usually paragraphs.
- Headings: if the PDF has bookmarks (a table of contents), a block whose text matches a
  bookmark title is that heading. Without bookmarks, we fall back to font size: text
  noticeably bigger than the body text is treated as a heading.
- Tables: detected with PyMuPDF's table finder and kept as "cell | cell | cell" rows, so
  the columns stay meaningful.
"""

import re
import unicodedata
from collections import Counter
from pathlib import Path

import pymupdf

from app.ingestion.extractors.base import ExtractedDocument, ExtractionError, Section

# Fewer characters than this per page on average means there's no real text layer.
MIN_CHARS_PER_PAGE = 20
# Without bookmarks, text at least this much bigger than body text counts as a heading.
HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 150
# A bullet glyph, or a dash followed by a space (so "-5 °C" is not a bullet).
_BULLET = re.compile(r"^(?:[•▪◦●■‣∙·]|[-–](?=\s))\s*")


def _normalise(text: str) -> str:
    """NFKC turns typographic ligatures like "ﬁ" into plain "fi", so search works."""
    return unicodedata.normalize("NFKC", text)


def _key(text: str) -> str:
    return " ".join(_normalise(text).lower().split())


def _block_text(block: dict) -> str:
    """Join a block's lines: one paragraph, except that bullet points stay on own lines."""
    out = ""
    for line in block["lines"]:
        text = _normalise("".join(span["text"] for span in line["spans"])).strip()
        if not text:
            continue
        if _BULLET.match(text):
            out += ("\n" if out else "") + "- " + _BULLET.sub("", text)
        elif out.endswith("-") and out[-2:-1].isalpha() and text[:1].islower():
            out = out[:-1] + text  # word hyphenated across lines: re-join
        else:
            out += (" " if out else "") + text
    return re.sub(r"[ \t]+", " ", out).strip()


def _block_size(block: dict) -> float:
    sizes = [
        span["size"] for line in block["lines"] for span in line["spans"] if span["text"].strip()
    ]
    return max(sizes) if sizes else 0.0


def _inside(bbox: tuple, rect: pymupdf.Rect) -> bool:
    centre = pymupdf.Point((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    return centre in rect


def _table_rows(page: pymupdf.Page, table) -> list[list[str | None]]:
    """Read each cell with the normal text reader (the table finder's own extraction
    can split words apart when letters are spaced out)."""
    return [[page.get_textbox(cell) if cell else None for cell in row.cells] for row in table.rows]


def _reliable_table(rows: list[list[str | None]]) -> bool:
    """Table detection can misfire (especially on tables without borders), merging words
    across columns and leaving cells empty. If too many cells are empty, don't trust it."""
    cells = [c for row in rows for c in row]
    if len(rows) < 2 or not cells:
        return False
    empty = sum(1 for c in cells if c is None or not c.strip())
    return empty / len(cells) <= 0.2


def _table_text(rows: list[list[str | None]]) -> str:
    lines = []
    for row in rows:
        cells = [" ".join(_normalise(c or "").split()) for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _continues(previous: Section, text: str, page_no: int) -> bool:
    """True if `text` (first block on a page) continues the previous page's last paragraph:
    the previous one ends mid-sentence and this one starts with a lowercase letter."""
    return (
        previous.last_page == page_no - 1
        and text[:1].islower()
        and not previous.text.rstrip().endswith((".", "!", "?", ":", "|"))
    )


def extract_pdf(path: Path) -> ExtractedDocument:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ExtractionError(f"Could not open PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise ExtractionError("This PDF is password-protected.")

        # Bookmark titles -> heading level (first occurrence wins).
        bookmarks: dict[str, int] = {}
        for level, title, _page in doc.get_toc():
            bookmarks.setdefault(_key(title), level)

        # Read every page once: text blocks (in reading order) and tables.
        pages = []
        size_chars: Counter[float] = Counter()
        for page in doc:
            # Detected tables, extracted once; unreliable ones are left to normal text blocks.
            tables = [
                (pymupdf.Rect(t.bbox), rows)
                for t in page.find_tables().tables
                if _reliable_table(rows := _table_rows(page, t))
            ]
            table_rects = [rect for rect, _ in tables]
            blocks = []
            for block in page.get_text("dict", sort=True)["blocks"]:
                if block["type"] != 0 or any(_inside(block["bbox"], r) for r in table_rects):
                    continue
                text = _block_text(block)
                if text:
                    size = round(_block_size(block), 1)
                    size_chars[size] += len(text)
                    blocks.append((block["bbox"][1], text, size))
            # Tables are placed at their vertical position among the text blocks.
            for rect, rows in tables:
                text = _table_text(rows)
                if text:
                    blocks.append((rect.y0, text, None))
            blocks.sort(key=lambda b: b[0])
            pages.append(blocks)

        # Font-size fallback: sizes clearly bigger than the body text are heading levels.
        body_size = size_chars.most_common(1)[0][0] if size_chars else 0.0
        heading_sizes = sorted(
            {s for s in size_chars if s >= body_size * HEADING_SIZE_RATIO}, reverse=True
        )

        def heading_level(text: str, size: float | None) -> int | None:
            if size is None or len(text) > MAX_HEADING_CHARS:
                return None
            if bookmarks:
                return bookmarks.get(_key(text))
            return heading_sizes.index(size) + 1 if size in heading_sizes else None

        sections: list[Section] = []
        headings: list[str] = []
        for page_no, blocks in enumerate(pages, start=1):
            for i, (_y, text, size) in enumerate(blocks):
                level = heading_level(text, size)
                if level is not None:
                    headings = headings[: level - 1] + [text]
                    continue
                if i == 0 and sections and _continues(sections[-1], text, page_no):
                    # A paragraph split by a page break: join it back together.
                    previous = sections.pop()
                    text = f"{previous.text} {text}"
                    sections.append(
                        Section(text, previous.heading_path, previous.page, page_end=page_no)
                    )
                else:
                    sections.append(Section(text, tuple(headings), page_no))

        total_chars = sum(len(s.text) for s in sections)
        if total_chars < MIN_CHARS_PER_PAGE * max(doc.page_count, 1):
            raise ExtractionError(
                "No readable text found. This looks like a scanned PDF (images of pages); "
                "OCR isn't supported yet."
            )
        return ExtractedDocument(sections=sections, page_count=doc.page_count)
