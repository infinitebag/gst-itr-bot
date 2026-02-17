"""Upload security module for file validation and basic malware scanning.

Validates uploaded PDFs and images in the GST/ITR WhatsApp bot by checking
file size, MIME type, magic bytes, filename safety, and (for PDFs) scanning
for potentially malicious embedded content such as JavaScript or launch actions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_IMAGE_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_PDF_SIZE = 25 * 1024 * 1024     # 25 MB

ALLOWED_MIME_TYPES: dict[str, str] = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}

# Magic byte signatures
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_PDF = b"%PDF-"
MAGIC_WEBP_PREFIX = b"RIFF"
MAGIC_WEBP_SUFFIX = b"WEBP"

# Map MIME types to their expected magic bytes validators
_MAGIC_VALIDATORS: dict[str, callable] = {}  # populated below

# Suspicious PDF byte patterns
_PDF_SUSPICIOUS_PATTERNS: list[bytes] = [
    b"/JavaScript",
    b"/Launch",
    b"/EmbeddedFile",
    b"/AA",
    b"/RichMedia",
]

# Path traversal / null-byte patterns in filenames
_UNSAFE_FILENAME_RE = re.compile(r"(\.\./|\\\\|\.\.\\|\x00)")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class UploadValidationResult:
    """Result of upload validation."""

    is_safe: bool
    reason: Optional[str]
    file_type: str
    file_size: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_magic_jpeg(data: bytes) -> bool:
    return data[:3] == MAGIC_JPEG


def _check_magic_png(data: bytes) -> bool:
    return data[:8] == MAGIC_PNG


def _check_magic_pdf(data: bytes) -> bool:
    return data[:5] == MAGIC_PDF


def _check_magic_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == MAGIC_WEBP_PREFIX and data[8:12] == MAGIC_WEBP_SUFFIX


_MAGIC_VALIDATORS = {
    "image/jpeg": _check_magic_jpeg,
    "image/png": _check_magic_png,
    "application/pdf": _check_magic_pdf,
    "image/webp": _check_magic_webp,
}


def _check_filename(filename: str) -> Optional[str]:
    """Return a rejection reason if the filename is unsafe, else ``None``."""
    if not filename:
        return "Filename is empty"
    if _UNSAFE_FILENAME_RE.search(filename):
        return f"Unsafe filename detected: {filename!r}"
    if "\x00" in filename:
        return "Filename contains null byte"
    return None


def _scan_pdf(data: bytes) -> Optional[str]:
    """Scan raw PDF bytes for suspicious patterns.

    Returns a reason string if a suspicious pattern is found, else ``None``.
    """
    for pattern in _PDF_SUSPICIOUS_PATTERNS:
        if pattern in data:
            return f"PDF contains suspicious pattern: {pattern.decode('ascii', errors='replace')}"

    # Special case: /OpenAction combined with /JS
    if b"/OpenAction" in data and b"/JS" in data:
        return "PDF contains /OpenAction with /JS (potential auto-execute JavaScript)"

    # Standalone /JS check (only trigger when not already caught by /JavaScript)
    if b"/JS" in data and b"/JavaScript" not in data:
        return "PDF contains suspicious pattern: /JS"

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_upload(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
) -> UploadValidationResult:
    """Validate an uploaded file for safety.

    Checks performed (in order):
    1. Non-empty payload
    2. Filename safety (path traversal, null bytes)
    3. MIME type allow-list
    4. File size limits
    5. Magic byte verification
    6. PDF-specific malware scan

    Returns an :class:`UploadValidationResult` indicating whether the file is
    safe and, if not, the reason for rejection.
    """
    file_size = len(file_bytes)

    # --- 1. Empty payload ------------------------------------------------
    if file_size == 0:
        return UploadValidationResult(
            is_safe=False,
            reason="File is empty",
            file_type="unknown",
            file_size=0,
        )

    # --- 2. Filename safety ----------------------------------------------
    filename_issue = _check_filename(filename)
    if filename_issue:
        return UploadValidationResult(
            is_safe=False,
            reason=filename_issue,
            file_type="unknown",
            file_size=file_size,
        )

    # --- 3. MIME type allow-list -----------------------------------------
    if mime_type not in ALLOWED_MIME_TYPES:
        return UploadValidationResult(
            is_safe=False,
            reason=f"MIME type not allowed: {mime_type}",
            file_type="unknown",
            file_size=file_size,
        )

    file_type = ALLOWED_MIME_TYPES[mime_type]

    # --- 4. File size limits ---------------------------------------------
    if file_type == "pdf":
        max_size = MAX_PDF_SIZE
    else:
        max_size = MAX_IMAGE_SIZE

    if file_size > max_size:
        limit_mb = max_size / (1024 * 1024)
        return UploadValidationResult(
            is_safe=False,
            reason=f"File exceeds {limit_mb:.0f} MB limit ({file_size} bytes)",
            file_type=file_type,
            file_size=file_size,
        )

    # --- 5. Magic bytes --------------------------------------------------
    validator = _MAGIC_VALIDATORS.get(mime_type)
    if validator and not validator(file_bytes):
        return UploadValidationResult(
            is_safe=False,
            reason=f"File content does not match claimed MIME type {mime_type}",
            file_type=file_type,
            file_size=file_size,
        )

    # --- 6. PDF malware scan ---------------------------------------------
    if file_type == "pdf":
        pdf_issue = _scan_pdf(file_bytes)
        if pdf_issue:
            return UploadValidationResult(
                is_safe=False,
                reason=pdf_issue,
                file_type=file_type,
                file_size=file_size,
            )

    # --- All checks passed -----------------------------------------------
    return UploadValidationResult(
        is_safe=True,
        reason=None,
        file_type=file_type,
        file_size=file_size,
    )
