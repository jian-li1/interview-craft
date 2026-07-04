"""Resume parser: plain-text path needs no external libs/network; validates size/type guards."""

from __future__ import annotations

import pytest

from app.services.resume_parser import MAX_RESUME_BYTES, ResumeParsingError, parse_resume


def test_parse_txt_resume():
    text = parse_resume(b"Experienced backend engineer.", filename="resume.txt", content_type="text/plain")
    assert text == "Experienced backend engineer."


def test_parse_empty_file_rejected():
    with pytest.raises(ResumeParsingError, match="empty"):
        parse_resume(b"", filename="resume.txt", content_type="text/plain")


def test_parse_oversized_file_rejected():
    oversized = b"a" * (MAX_RESUME_BYTES + 1)
    with pytest.raises(ResumeParsingError, match="5MB"):
        parse_resume(oversized, filename="resume.txt", content_type="text/plain")


def test_parse_unsupported_type_rejected():
    with pytest.raises(ResumeParsingError, match="unsupported"):
        parse_resume(b"binary junk", filename="resume.exe", content_type="application/octet-stream")


def test_parse_txt_falls_back_to_extension_when_content_type_missing():
    text = parse_resume(b"Some resume text", filename="resume.txt", content_type=None)
    assert text == "Some resume text"


def test_parse_txt_latin1_fallback_on_bad_utf8():
    raw = "café".encode("latin-1")
    text = parse_resume(raw, filename="resume.txt", content_type="text/plain")
    assert "caf" in text


def test_parse_blank_whitespace_txt_rejected():
    with pytest.raises(ResumeParsingError, match="empty"):
        parse_resume(b"   \n\t  ", filename="resume.txt", content_type="text/plain")
