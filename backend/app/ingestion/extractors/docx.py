"""Word (.docx) extraction with python-docx.

Word files have real structure: paragraphs with styles ("Heading 1", "List Bullet"...)
and tables. We walk the document body in order, track the current heading path from
heading styles, and emit paragraphs, list items and tables as sections. Word files
don't store page numbers (pages depend on the viewer's layout), so `page` stays None.
"""

import re
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.extractors.base import ExtractedDocument, ExtractionError, Section


def _heading_level(paragraph: Paragraph) -> int | None:
    style = (paragraph.style.name if paragraph.style is not None else "") or ""
    if style == "Title":
        return 1
    match = re.fullmatch(r"Heading (\d)", style)
    return int(match.group(1)) if match else None


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if not cells or cells[-1] != text:  # merged cells repeat; keep one copy
                cells.append(text)
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def extract_docx(path: Path) -> ExtractedDocument:
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ExtractionError(f"Could not open Word document: {exc}") from exc

    sections: list[Section] = []
    headings: list[str] = []
    pending_list: list[str] = []  # consecutive list items are kept together

    def flush_list() -> None:
        if pending_list:
            sections.append(Section("\n".join(pending_list), tuple(headings)))
            pending_list.clear()

    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            level = _heading_level(paragraph)
            if level is not None:
                flush_list()
                headings = headings[: level - 1] + [text]
            elif "List" in (paragraph.style.name if paragraph.style is not None else ""):
                pending_list.append(f"- {text}")
            else:
                flush_list()
                sections.append(Section(text, tuple(headings)))
        elif tag == "tbl":
            flush_list()
            text = _table_text(Table(element, document))
            if text:
                sections.append(Section(text, tuple(headings)))
    flush_list()

    if not sections:
        raise ExtractionError("This Word document contains no text.")
    return ExtractedDocument(sections=sections)
