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
    """Determine which parser to use ("pdf"/"docx"/"txt") for an uploaded resume.

    Prefers the declared `content_type` (from the multipart upload) and falls back to
    sniffing the filename extension when the content type is missing or untrustworthy
    (e.g. a generic `application/octet-stream` from some browsers/clients).

    Args:
        filename (str): The original uploaded filename, used for extension fallback.
        content_type (str | None): The MIME type reported by the upload, if any.

    Returns:
        str: One of "pdf", "docx", or "txt".

    Raises:
        ResumeParsingError: If neither the content type nor the filename extension
            matches a supported resume format.
    """
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
    """Parse resume bytes into plain text.

    Performs the size/type validation described in spec 01 §8 before dispatching to the
    format-specific parser. Nothing is ever written to disk; parsing happens entirely
    from the in-memory `raw_bytes` buffer.

    Args:
        raw_bytes (bytes): The raw uploaded file contents.
        filename (str): The original uploaded filename (used for extension fallback
            when `content_type` is missing/unrecognized).
        content_type (str | None): The MIME type reported by the upload, if any.

    Returns:
        str: The extracted plain-text resume content.

    Raises:
        ResumeParsingError: If the file is empty, exceeds `MAX_RESUME_BYTES`, has an
            unsupported type, or fails to parse / yields no extractable text.
    """
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
    """Extract plain text from an in-memory PDF file using pypdf.

    Args:
        raw_bytes (bytes): The raw PDF file contents.

    Returns:
        str: The concatenated, stripped text of all pages, joined by newlines.

    Raises:
        ResumeParsingError: If the `pypdf` dependency is unavailable, the PDF fails to
            parse, or no extractable text is found (e.g. a scanned image PDF with no
            text layer).
    """
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
    """Extract plain text from an in-memory DOCX file using python-docx.

    Args:
        raw_bytes (bytes): The raw DOCX (Office Open XML) file contents.

    Returns:
        str: The concatenated, stripped text of all paragraphs, joined by newlines.

    Raises:
        ResumeParsingError: If the `docx` dependency is unavailable, the file fails to
            parse, or no extractable text is found.
    """
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
    """Decode an in-memory plain-text file, tolerating non-UTF-8 encodings.

    Attempts UTF-8 first; falls back to latin-1 (which can decode any byte sequence,
    substituting replacement characters as needed) so odd legacy encodings don't crash
    the upload outright.

    Args:
        raw_bytes (bytes): The raw text file contents.

    Returns:
        str: The decoded, stripped text content.

    Raises:
        ResumeParsingError: If the decoded text is empty after stripping.
    """
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")
    text = text.strip()
    if not text:
        raise ResumeParsingError("uploaded text file is empty")
    return text
