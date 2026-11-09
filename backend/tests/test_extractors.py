"""Extraction: each format becomes the same list of Sections with headings and pages."""

import pymupdf
import pytest

from app.ingestion.extractors import ExtractionError, FileType, detect_file_type, extract
from scripts.make_samples import SampleDoc, to_markdown, write_docx, write_pdf

DOC = SampleDoc(
    "Policy",
    [
        ("h1", "Leave"),
        ("h2", "Parental"),
        ("p", "Primary caregivers get 16 weeks of paid leave."),
        ("h2", "Sick"),
        ("p", "Up to 10 days of sick leave per year."),
        ("ul", ["First item", "Second item"]),
        ("h1", "Hotels"),
        ("table", [["City", "Cap"], ["London", "$250"], ["Elsewhere", "$180"]]),
    ],
)


def heading_of(sections, needle: str) -> tuple[str, ...]:
    return next(s.heading_path for s in sections if needle in s.text)


@pytest.fixture(params=["md", "docx", "pdf"])
def extracted(request, tmp_path):
    """The same content in all three formats, so every test runs once per format."""
    path = tmp_path / f"policy.{request.param}"
    if request.param == "md":
        path.write_text(to_markdown(DOC))
        mime = FileType.MARKDOWN
    elif request.param == "docx":
        write_docx(DOC, path)
        mime = FileType.DOCX
    else:
        write_pdf(DOC, path)
        mime = FileType.PDF
    return extract(path, mime.value)


def test_headings_are_tracked(extracted):
    sections = extracted.sections
    assert heading_of(sections, "16 weeks") == ("Policy", "Leave", "Parental")
    assert heading_of(sections, "10 days") == ("Policy", "Leave", "Sick")
    assert heading_of(sections, "London") == ("Policy", "Hotels")


def test_headings_are_not_body_text(extracted):
    assert not any(
        s.text.strip() in {"Leave", "Parental", "Sick", "Hotels"} for s in extracted.sections
    )


def test_tables_keep_their_columns(extracted):
    table = next(s.text for s in extracted.sections if "London" in s.text)
    assert table == "City: London; Cap: $250\nCity: Elsewhere; Cap: $180"


def test_list_items_stay_on_separate_lines(extracted):
    text = next(s.text for s in extracted.sections if "First item" in s.text)
    assert "- First item\n- Second item" in text


def test_pdf_pages_and_ligatures(tmp_path):
    path = tmp_path / "long.pdf"
    long_paragraph = " ".join(f"Sentence {i} about the finance office." for i in range(400))
    write_pdf(
        SampleDoc(
            "Long", [("h1", "Intro"), ("p", long_paragraph), ("h1", "End"), ("p", "Last words.")]
        ),
        path,
    )
    result = extract(path, FileType.PDF.value)
    assert result.page_count and result.page_count >= 2
    # The paragraph spans a page break but comes back as ONE section starting on page 1.
    long = [s for s in result.sections if "Sentence 0 " in s.text]
    assert len(long) == 1 and long[0].page == 1
    assert long[0].page_end == result.page_count
    assert "Sentence 399 " in long[0].text
    assert result.sections[-1].page == result.page_count
    assert "ﬁ" not in "".join(s.text for s in result.sections)  # ligatures normalised


def test_pdf_without_bookmarks_uses_font_sizes(tmp_path):
    path = tmp_path / "no-toc.pdf"
    write_pdf(DOC, path, with_bookmarks=False)
    sections = extract(path, FileType.PDF.value).sections
    assert heading_of(sections, "16 weeks") == ("Policy", "Leave", "Parental")


def test_scanned_pdf_is_rejected(tmp_path):
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0.5, 0.5, 0.5))  # an "image", no text
    doc.save(path)
    with pytest.raises(ExtractionError, match="scanned"):
        extract(path, FileType.PDF.value)


def test_markdown_front_matter_and_code_blocks(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("---\ntitle: x\n---\n# Setup\n\nRun this:\n\n```bash\nmake install\n```\n")
    sections = extract(path, FileType.MARKDOWN.value).sections
    assert [s.text for s in sections] == ["Run this:", "```bash\nmake install\n```"]
    assert all(s.heading_path == ("Setup",) for s in sections)


def test_empty_markdown_is_rejected(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("# Only a heading\n")
    with pytest.raises(ExtractionError):
        extract(path, FileType.MARKDOWN.value)


class TestDetectFileType:
    def test_accepts_real_files(self, tmp_path):
        write_docx(DOC, tmp_path / "a.docx")
        write_pdf(DOC, tmp_path / "a.pdf")
        assert detect_file_type("a.docx", (tmp_path / "a.docx").read_bytes()) == FileType.DOCX
        assert detect_file_type("A.PDF", (tmp_path / "a.pdf").read_bytes()) == FileType.PDF
        assert detect_file_type("notes.md", "# Héllo".encode()) == FileType.MARKDOWN

    def test_rejects_renamed_or_unsupported_files(self):
        assert detect_file_type("report.pdf", b"MZ\x90\x00 an exe") is None
        assert detect_file_type("report.docx", b"PK\x03\x04 not really a zip") is None
        assert detect_file_type("notes.md", b"\x00\x01binary") is None
        assert detect_file_type("notes.md", b"\xff\xfe invalid utf8") is None
        assert detect_file_type("photo.png", b"\x89PNG") is None
        assert detect_file_type("noext", b"%PDF-1.7") is None
