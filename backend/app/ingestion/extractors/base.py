"""The common shape every extractor produces.

PDFs, Word files and Markdown store text very differently. Each extractor translates
its format into the same simple list of `Section`s, so the chunker (and everything after
it) never needs to know which format a document came from.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Section:
    """One block of text (usually a paragraph, list, table or code block)."""

    text: str
    heading_path: tuple[str, ...] = ()  # e.g. ("Leave Policy", "Parental leave")
    page: int | None = None  # 1-based page number where it starts; PDFs only
    page_end: int | None = None  # where it ends, if different (paragraph across a page break)

    @property
    def last_page(self) -> int | None:
        return self.page_end or self.page


@dataclass
class ExtractedDocument:
    sections: list[Section] = field(default_factory=list)
    page_count: int | None = None


class ExtractionError(Exception):
    """A problem with the file itself (shown to the user), e.g. a scanned PDF with no text."""
