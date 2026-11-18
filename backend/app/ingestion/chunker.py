"""Split extracted sections into chunks: the pieces we embed, search and cite.

Why chunk at all? An embedding captures the meaning of one piece of text. A whole
50-page document squashed into one embedding is too vague to match a specific question,
and too big to paste into the model's prompt. Small focused chunks match better and let
citations point at the exact passage.

How this chunker works:
1. Sections that share the same heading path form a "topic". A chunk never spans two
   topics, so each chunk is about one thing and its heading describes it accurately.
2. Within a topic, sections are packed into a chunk until adding the next one would
   go over the target size (~500 tokens).
3. A section that is too big on its own is split recursively: by paragraph, then by
   line, then by sentence, then by word, so cuts land at the most natural place.
4. When a topic continues into a new chunk, the new chunk starts with the last couple
   of sentences of the previous one (~75 tokens of "overlap"), so a fact that straddles
   the cut still appears whole in at least one chunk.
"""

import re
from dataclasses import dataclass
from itertools import groupby

from app.ingestion.extractors.base import Section

# Separators tried in order when a piece of text is too big, from most to least natural.
_PARAGRAPH = re.compile(r"\n\s*\n")
_LINE = re.compile(r"\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")
_WORD = re.compile(r"\s+")
_SPLITTERS: list[tuple[re.Pattern[str], str]] = [
    (_PARAGRAPH, "\n\n"),
    (_LINE, "\n"),
    (_SENTENCE, " "),
    (_WORD, " "),
]


def estimate_tokens(text: str) -> int:
    """Rough token count. A token is ~4 characters of English (about 3/4 of a word).
    Exact counts depend on the model's tokenizer; an estimate is fine for sizing."""
    return max(1, round(len(text) / 4))


@dataclass(frozen=True)
class TextChunk:
    text: str
    heading_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    token_count: int


@dataclass(frozen=True)
class _Piece:
    """A unit of text small enough to fit in a chunk, plus how to join it to the
    previous piece (a paragraph break, newline or space)."""

    text: str
    page: int | None
    page_end: int | None
    joiner: str


def _split(text: str, max_tokens: int, depth: int = 0) -> list[tuple[str, str]]:
    """Recursively split text into (piece, joiner) pairs each within max_tokens."""
    if estimate_tokens(text) <= max_tokens:
        return [(text, "\n\n")]
    for pattern, joiner in _SPLITTERS[depth:]:
        depth += 1
        parts = [p for p in pattern.split(text) if p.strip()]
        if len(parts) > 1:
            pieces: list[tuple[str, str]] = []
            for i, part in enumerate(parts):
                sub = _split(part.strip(), max_tokens, depth)
                if i > 0:  # first sub-piece of a later part joins with this separator
                    sub[0] = (sub[0][0], joiner)
                pieces.extend(sub)
            return pieces
    # A single enormous "word" (e.g. a long URL or base64 blob): hard cut.
    size = max_tokens * 4
    return [(text[i : i + size], "" if i else "\n\n") for i in range(0, len(text), size)]


def _overlap_tail(text: str, overlap_tokens: int) -> str:
    """The last few sentences of `text`, up to about `overlap_tokens`."""
    if overlap_tokens <= 0:
        return ""
    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    tail: list[str] = []
    for sentence in reversed(sentences):
        if estimate_tokens(" ".join([sentence, *tail])) > overlap_tokens:
            break
        tail.insert(0, sentence)
    if tail:
        return " ".join(tail).strip()
    # No sentence fits (one very long sentence): take the last ~overlap_tokens worth of
    # characters, starting at a word boundary when there is one.
    tail = text[-overlap_tokens * 4 :]
    if " " in tail and not tail.startswith(" "):
        tail = tail.split(" ", 1)[1]
    return tail.strip()


def _make_chunk(pieces: list[_Piece], heading_path: tuple[str, ...]) -> TextChunk:
    text = pieces[0].text
    for piece in pieces[1:]:
        text += piece.joiner + piece.text
    starts = [p.page for p in pieces if p.page is not None]
    ends = [p.page_end for p in pieces if p.page_end is not None]
    return TextChunk(
        text=text,
        heading_path=heading_path,
        page_start=min(starts) if starts else None,
        page_end=max(ends) if ends else None,
        token_count=estimate_tokens(text),
    )


def chunk_sections(
    sections: list[Section], target_tokens: int = 500, overlap_tokens: int = 75
) -> list[TextChunk]:
    if overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be smaller than target_tokens")

    chunks: list[TextChunk] = []
    for heading_path, topic in groupby(sections, key=lambda s: s.heading_path):
        # Break the topic into pieces that each fit in a chunk.
        pieces = [
            _Piece(text, section.page, section.last_page, joiner)
            for section in topic
            for text, joiner in _split(section.text.strip(), target_tokens - overlap_tokens)
        ]

        # Pack pieces into chunks, carrying an overlap into each continuation chunk.
        # Sizes are measured on the joined text (separators included) in characters.
        max_chars = target_tokens * 4
        current: list[_Piece] = []
        current_chars = 0
        has_new_content = False
        for piece in pieces:
            added = len(piece.text) + (len(piece.joiner) if current else 0)
            if has_new_content and current_chars + added > max_chars:
                chunk = _make_chunk(current, heading_path)
                chunks.append(chunk)
                tail = _overlap_tail(chunk.text, overlap_tokens)
                last = current[-1]
                current = [_Piece(tail, last.page_end, last.page_end, "")] if tail else []
                current_chars = len(tail)
                added = len(piece.text) + (len(piece.joiner) if current else 0)
                has_new_content = False
            current.append(piece)
            current_chars += added
            has_new_content = True
        if has_new_content:
            chunks.append(_make_chunk(current, heading_path))
    return chunks
