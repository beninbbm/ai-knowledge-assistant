"""Markdown extraction with markdown-it-py.

We parse the file only to find its structure (headings and top-level blocks), then
slice each block's *original source lines*, so lists, tables and code blocks keep their
exact formatting for display.
"""

import re
from pathlib import Path

from markdown_it import MarkdownIt

from app.ingestion.extractors.base import (
    ExtractedDocument,
    ExtractionError,
    Section,
    format_table,
)

_parser = MarkdownIt("commonmark").enable("table")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _table_rows(tokens: list, start: int) -> list[list[str]]:
    """Cell texts of the table whose table_open token is at `start`."""
    rows: list[list[str]] = []
    for token in tokens[start + 1 :]:
        if token.type == "table_close":
            break
        if token.type == "tr_open":
            rows.append([])
        elif token.type == "inline" and rows:
            rows[-1].append(token.content.strip())
    return rows


def extract_markdown(path: Path) -> ExtractedDocument:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError("Markdown file is not valid UTF-8 text.") from exc

    # Drop YAML front matter but keep line numbers aligned with the source.
    front = _FRONT_MATTER.match(source)
    if front:
        source = "\n" * front.group(0).count("\n") + source[front.end() :]
    lines = source.splitlines()

    sections: list[Section] = []
    headings: list[str] = []
    tokens = _parser.parse(source)
    for i, token in enumerate(tokens):
        if token.level != 0 or token.nesting == -1 or token.map is None:
            continue  # only top-level opening/self-contained blocks
        if token.type == "heading_open":
            level = int(token.tag[1])  # "h2" -> 2
            title = tokens[i + 1].content.strip()
            headings = headings[: level - 1] + [title]
            continue
        if token.type == "hr":
            continue
        if token.type == "table_open":
            text = format_table(_table_rows(tokens, i))
            if text:
                sections.append(Section(text, tuple(headings)))
            continue
        start, end = token.map
        text = "\n".join(lines[start:end]).strip()
        if text:
            sections.append(Section(text, tuple(headings)))

    if not sections:
        raise ExtractionError("This Markdown file contains no text.")
    return ExtractedDocument(sections=sections)
