"""Tests for the upload security / file validation module."""

import pytest

from app.domain.services.upload_security import (
    UploadValidationResult,
    validate_upload,
    MAX_IMAGE_SIZE,
    MAX_PDF_SIZE,
    MAGIC_JPEG,
    MAGIC_PNG,
    MAGIC_PDF,
)


# ---------------------------------------------------------------------------
# Helpers to build minimal valid file payloads
# ---------------------------------------------------------------------------

def _make_jpeg(size: int = 128) -> bytes:
    """Return bytes that start with a valid JPEG SOI marker."""
    header = MAGIC_JPEG
    return header + b"\x00" * (size - len(header))


def _make_png(size: int = 128) -> bytes:
    """Return bytes that start with a valid PNG signature."""
    header = MAGIC_PNG
    return header + b"\x00" * (size - len(header))


def _make_pdf(extra: bytes = b"", size: int = 256) -> bytes:
    """Return bytes that start with a valid PDF header.

    *extra* is injected after the header (useful for malicious-pattern tests).
    """
    header = MAGIC_PDF + b"1.4\n"
    body = header + extra
    if len(body) < size:
        body += b"\x00" * (size - len(body))
    return body


def _make_webp(size: int = 128) -> bytes:
    """Return bytes with a valid WebP RIFF header."""
    # RIFF....WEBP
    header = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP"
    return header + b"\x00" * (size - len(header))


# ---------------------------------------------------------------------------
# Valid files pass validation
# ---------------------------------------------------------------------------

def test_valid_jpeg_passes():
    result = validate_upload(_make_jpeg(), "photo.jpg", "image/jpeg")
    assert result.is_safe is True
    assert result.reason is None
    assert result.file_type == "jpeg"
    assert result.file_size == 128


def test_valid_png_passes():
    result = validate_upload(_make_png(), "receipt.png", "image/png")
    assert result.is_safe is True
    assert result.file_type == "png"


def test_valid_pdf_passes():
    result = validate_upload(_make_pdf(), "invoice.pdf", "application/pdf")
    assert result.is_safe is True
    assert result.file_type == "pdf"


def test_valid_webp_passes():
    result = validate_upload(_make_webp(), "image.webp", "image/webp")
    assert result.is_safe is True
    assert result.file_type == "webp"


# ---------------------------------------------------------------------------
# Empty file rejected
# ---------------------------------------------------------------------------

def test_empty_file_rejected():
    result = validate_upload(b"", "empty.pdf", "application/pdf")
    assert result.is_safe is False
    assert "empty" in result.reason.lower()
    assert result.file_type == "unknown"
    assert result.file_size == 0


# ---------------------------------------------------------------------------
# File size limits
# ---------------------------------------------------------------------------

def test_oversized_image_rejected():
    big = _make_jpeg(MAX_IMAGE_SIZE + 1)
    result = validate_upload(big, "huge.jpg", "image/jpeg")
    assert result.is_safe is False
    assert "10 MB" in result.reason
    assert result.file_type == "jpeg"


def test_oversized_pdf_rejected():
    big = _make_pdf(size=MAX_PDF_SIZE + 1)
    result = validate_upload(big, "huge.pdf", "application/pdf")
    assert result.is_safe is False
    assert "25 MB" in result.reason
    assert result.file_type == "pdf"


def test_image_at_exact_limit_passes():
    exact = _make_jpeg(MAX_IMAGE_SIZE)
    result = validate_upload(exact, "exact.jpg", "image/jpeg")
    assert result.is_safe is True


# ---------------------------------------------------------------------------
# MIME type validation
# ---------------------------------------------------------------------------

def test_invalid_mime_type_rejected():
    result = validate_upload(b"PK\x03\x04", "macro.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert result.is_safe is False
    assert "MIME type not allowed" in result.reason


def test_text_html_mime_rejected():
    result = validate_upload(b"<html>", "page.html", "text/html")
    assert result.is_safe is False
    assert "MIME type not allowed" in result.reason


# ---------------------------------------------------------------------------
# Magic bytes mismatch
# ---------------------------------------------------------------------------

def test_magic_bytes_mismatch_jpeg():
    """Claiming image/jpeg but content starts with PNG magic."""
    result = validate_upload(_make_png(), "fake.jpg", "image/jpeg")
    assert result.is_safe is False
    assert "does not match" in result.reason


def test_magic_bytes_mismatch_png():
    """Claiming image/png but content starts with JPEG magic."""
    result = validate_upload(_make_jpeg(), "fake.png", "image/png")
    assert result.is_safe is False
    assert "does not match" in result.reason


def test_magic_bytes_mismatch_pdf():
    """Claiming application/pdf but content starts with JPEG magic."""
    result = validate_upload(_make_jpeg(), "fake.pdf", "application/pdf")
    assert result.is_safe is False
    assert "does not match" in result.reason


# ---------------------------------------------------------------------------
# Filename safety (path traversal, null bytes)
# ---------------------------------------------------------------------------

def test_path_traversal_rejected():
    result = validate_upload(_make_jpeg(), "../../etc/passwd", "image/jpeg")
    assert result.is_safe is False
    assert "Unsafe filename" in result.reason


def test_null_byte_in_filename_rejected():
    result = validate_upload(_make_jpeg(), "photo.jpg\x00.exe", "image/jpeg")
    assert result.is_safe is False
    assert "Unsafe filename" in result.reason or "null byte" in result.reason.lower()


def test_backslash_traversal_rejected():
    result = validate_upload(_make_jpeg(), "..\\..\\windows\\system32", "image/jpeg")
    assert result.is_safe is False
    assert "Unsafe filename" in result.reason


# ---------------------------------------------------------------------------
# PDF malware scanning
# ---------------------------------------------------------------------------

def test_pdf_with_javascript_rejected():
    payload = _make_pdf(extra=b" /JavaScript (alert('xss'))  ")
    result = validate_upload(payload, "evil.pdf", "application/pdf")
    assert result.is_safe is False
    assert "/JavaScript" in result.reason


def test_pdf_with_launch_rejected():
    payload = _make_pdf(extra=b" /Launch /Win << /F (cmd.exe) >>  ")
    result = validate_upload(payload, "evil.pdf", "application/pdf")
    assert result.is_safe is False
    assert "/Launch" in result.reason


def test_pdf_with_embedded_file_rejected():
    payload = _make_pdf(extra=b" /EmbeddedFile /Type /Filespec  ")
    result = validate_upload(payload, "evil.pdf", "application/pdf")
    assert result.is_safe is False
    assert "/EmbeddedFile" in result.reason


def test_pdf_with_openaction_js_rejected():
    payload = _make_pdf(extra=b" /OpenAction << /S /JS /JS (app.alert('hi')) >>  ")
    result = validate_upload(payload, "evil.pdf", "application/pdf")
    assert result.is_safe is False
    # Should mention either /OpenAction+/JS or /JavaScript
    assert "/JS" in result.reason or "/OpenAction" in result.reason


def test_pdf_with_aa_rejected():
    payload = _make_pdf(extra=b" /AA << /O << /S /JavaScript /JS (void(0)) >> >>  ")
    result = validate_upload(payload, "evil.pdf", "application/pdf")
    assert result.is_safe is False
    assert "/AA" in result.reason or "/JavaScript" in result.reason


def test_pdf_with_richmedia_rejected():
    payload = _make_pdf(extra=b" /RichMedia /Type /Annot  ")
    result = validate_upload(payload, "evil.pdf", "application/pdf")
    assert result.is_safe is False
    assert "/RichMedia" in result.reason


def test_clean_pdf_passes():
    """A PDF without any suspicious patterns should pass."""
    payload = _make_pdf(extra=b" /Type /Page /Contents 1 0 R  ")
    result = validate_upload(payload, "clean.pdf", "application/pdf")
    assert result.is_safe is True


# ---------------------------------------------------------------------------
# Result dataclass shape
# ---------------------------------------------------------------------------

def test_result_has_expected_fields():
    result = validate_upload(_make_jpeg(), "photo.jpg", "image/jpeg")
    assert isinstance(result, UploadValidationResult)
    assert isinstance(result.is_safe, bool)
    assert isinstance(result.file_type, str)
    assert isinstance(result.file_size, int)
    # reason is None when safe
    assert result.reason is None
