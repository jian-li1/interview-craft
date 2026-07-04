"""In-memory resume parsing for pdf/docx/plain-text uploads.

Enforces a 5MB size limit and content-type allowlist per spec 01 §8. Never writes the
uploaded file to disk — everything is parsed from an in-memory buffer.
"""

from __future__ import annotations

import io

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_RESUME_BYTES = 5 * 1024 * 1024  # 5MB

_ALLOWED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}

_EXTENSION_FALLBACK = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
}


class ResumeParsingError(Exception):
    """Raised for any user-facing resume upload/parsing failure (bad type, too large, corrupt)."""


def _resolve_kind(filename: str, content_type: str | None) -> str:
    if content_type in _ALLOWED_CONTENT_TYPES:
        return _ALLOWED_CONTENT_TYPES[content_type]
    lowered = filename.lower()
    for ext, kind in _EXTENSION_FALLBACK.items():
        if lowered.endswith(ext):
            return kind
    raise ResumeParsingError(
        "unsupported file type; only PDF, DOCX, and plain text resumes are accepted"
    )


def parse_resume(raw_bytes: bytes, *, filename: str, content_type: str | None) -> str:
    """Parse resume bytes into plain text. Raises ResumeParsingError on any failure."""
    if len(raw_bytes) == 0:
        raise ResumeParsingError("uploaded file is empty")
    if len(raw_bytes) > MAX_RESUME_BYTES:
        raise ResumeParsingError("file exceeds the 5MB size limit")

    kind = _resolve_kind(filename, content_type)

    if kind == "pdf":
        return _parse_pdf(raw_bytes)
    if kind == "docx":
        return _parse_docx(raw_bytes)
    return _parse_txt(raw_bytes)


def _parse_pdf(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ResumeParsingError("PDF parsing is unavailable on this server") from exc

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ResumeParsingError(f"failed to parse PDF: {exc}") from exc

    text = "\n".join(pages_text).strip()
    if not text:
        raise ResumeParsingError("no extractable text found in PDF (it may be a scanned image)")
    return text


def _parse_docx(raw_bytes: bytes) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise ResumeParsingError("DOCX parsing is unavailable on this server") from exc

    try:
        document = docx.Document(io.BytesIO(raw_bytes))
        paragraphs = [p.text for p in document.paragraphs]
    except Exception as exc:
        raise ResumeParsingError(f"failed to parse DOCX: {exc}") from exc

    text = "\n".join(paragraphs).strip()
    if not text:
        raise ResumeParsingError("no extractable text found in DOCX")
    return text


def _parse_txt(raw_bytes: bytes) -> str:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")
    text = text.strip()
    if not text:
        raise ResumeParsingError("uploaded text file is empty")
    return text
