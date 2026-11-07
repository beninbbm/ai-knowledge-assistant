"""Pick the right extractor for a file, based on its detected type."""

import io
import zipfile
from enum import StrEnum
from pathlib import Path

from app.ingestion.extractors.base import ExtractedDocument, ExtractionError, Section
from app.ingestion.extractors.docx import extract_docx
from app.ingestion.extractors.markdown import extract_markdown
from app.ingestion.extractors.pdf import extract_pdf

__all__ = [
    "ExtractedDocument",
    "ExtractionError",
    "FileType",
    "Section",
    "detect_file_type",
    "extract",
]


class FileType(StrEnum):
    """Supported types, stored on the document as its MIME type."""

    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    MARKDOWN = "text/markdown"


def detect_file_type(filename: str, data: bytes) -> FileType | None:
    """Check BOTH the extension and the actual content ("magic bytes"), so a renamed
    file (e.g. an .exe called report.pdf) is rejected."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        return FileType.PDF
    if suffix == ".docx" and data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" in zf.namelist():
                    return FileType.DOCX
        except zipfile.BadZipFile:
            return None
    if suffix in {".md", ".markdown"} and b"\x00" not in data:
        try:
            data.decode("utf-8")
            return FileType.MARKDOWN
        except UnicodeDecodeError:
            return None
    return None


def extract(path: Path, mime_type: str) -> ExtractedDocument:
    match FileType(mime_type):
        case FileType.PDF:
            return extract_pdf(path)
        case FileType.DOCX:
            return extract_docx(path)
        case FileType.MARKDOWN:
            return extract_markdown(path)
