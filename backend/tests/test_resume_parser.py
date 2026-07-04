"""Resume parser: plain-text path needs no external libs/network; validates size/type guards."""

from __future__ import annotations

import pytest

from app.services.resume_parser import MAX_RESUME_BYTES, ResumeParsingError, parse_resume


def test_parse_txt_resume():
    """Verify a plain-text resume is decoded and returned as-is."""
    text = parse_resume(b"Experienced backend engineer.", filename="resume.txt", content_type="text/plain")
    assert text == "Experienced backend engineer."


def test_parse_empty_file_rejected():
    """Verify an empty file raises `ResumeParsingError` mentioning "empty"."""
    with pytest.raises(ResumeParsingError, match="empty"):
        parse_resume(b"", filename="resume.txt", content_type="text/plain")


def test_parse_oversized_file_rejected():
    """Verify a file over `MAX_RESUME_BYTES` raises `ResumeParsingError` mentioning "5MB"."""
    oversized = b"a" * (MAX_RESUME_BYTES + 1)
    with pytest.raises(ResumeParsingError, match="5MB"):
        parse_resume(oversized, filename="resume.txt", content_type="text/plain")


def test_parse_unsupported_type_rejected():
    """Verify an unsupported filename/content-type combination is rejected as "unsupported"."""
    with pytest.raises(ResumeParsingError, match="unsupported"):
        parse_resume(b"binary junk", filename="resume.exe", content_type="application/octet-stream")


def test_parse_txt_falls_back_to_extension_when_content_type_missing():
    """Verify a missing content_type still parses correctly via the .txt file extension."""
    text = parse_resume(b"Some resume text", filename="resume.txt", content_type=None)
    assert text == "Some resume text"


def test_parse_txt_latin1_fallback_on_bad_utf8():
    """Verify bytes that aren't valid UTF-8 still decode via a latin-1 fallback."""
    raw = "café".encode("latin-1")
    text = parse_resume(raw, filename="resume.txt", content_type="text/plain")
    assert "caf" in text


def test_parse_blank_whitespace_txt_rejected():
    """Verify a file containing only whitespace is treated as empty and rejected."""
    with pytest.raises(ResumeParsingError, match="empty"):
        parse_resume(b"   \n\t  ", filename="resume.txt", content_type="text/plain")
