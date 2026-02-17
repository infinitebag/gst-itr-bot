# app/domain/services/pii_masking.py
"""PII masking utilities for safe logging and WhatsApp display.

All functions are synchronous string operations.  They never raise on
invalid input -- they return the value unchanged (or empty string) when
the format is unrecognised.
"""

import re

# ---------------------------------------------------------------------------
# Mask character — bullet (•) for user-facing display
# ---------------------------------------------------------------------------
MASK_CHAR = "\u2022"  # bullet •

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# GSTIN: 2-digit state code + 10-char PAN + 1 entity + Z + 1 check digit
_GSTIN_RE = re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")

# PAN: 5 alpha + 4 digits + 1 alpha
_PAN_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")

# Indian phone: optional +91 / 91 prefix, then 10 digits starting with 6-9
_PHONE_RE = re.compile(r"\b(?:\+?91[-\s]?)?([6-9]\d{9})\b")

# Bank account: 9-18 consecutive digits (not preceded/followed by alpha)
_BANK_ACCOUNT_RE = re.compile(r"(?<![A-Za-z0-9])(\d{9,18})(?![A-Za-z0-9])")

# Email: simple pattern for masking (not validation)
_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


# ---------------------------------------------------------------------------
# Individual masking helpers
# ---------------------------------------------------------------------------

def mask_gstin(gstin: str) -> str:
    """Mask a GSTIN, showing only first 2 + last 3 characters.

    Example: ``36AABCU9603R1ZM`` -> ``36••••••••••1ZM``
    """
    if not gstin or len(gstin) != 15:
        return gstin or ""
    return gstin[:2] + MASK_CHAR * 10 + gstin[12:]


def mask_pan(pan: str) -> str:
    """Mask a PAN, showing only first 2 + last 1 character.

    Example: ``ABCDE1234K`` -> ``AB•••••••K``
    """
    if not pan or len(pan) != 10:
        return pan or ""
    return pan[:2] + MASK_CHAR * 7 + pan[9:]


def mask_phone(phone: str) -> str:
    """Mask a phone number, showing only last 4 digits.

    Handles bare 10-digit, ``+91``-prefixed, and ``91``-prefixed formats.
    Example: ``9876543210`` -> ``••••••3210``
    """
    if not phone:
        return ""
    digits = re.sub(r"[^0-9]", "", phone)
    if len(digits) < 4:
        return MASK_CHAR * len(digits)
    return MASK_CHAR * (len(digits) - 4) + digits[-4:]


def mask_bank_account(account: str) -> str:
    """Mask a bank account number, showing only last 4 digits.

    Example: ``12345678`` -> ``••••5678``
    """
    if not account:
        return ""
    digits = re.sub(r"[^0-9]", "", account)
    if len(digits) < 4:
        return MASK_CHAR * len(digits)
    return MASK_CHAR * (len(digits) - 4) + digits[-4:]


def mask_email(email: str) -> str:
    """Mask an email address, showing first 2 chars of local part + domain.

    Example: ``subash.t@gmail.com`` -> ``su••••@gmail.com``
    """
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local
    else:
        masked_local = local[:2] + MASK_CHAR * (len(local) - 2)
    return f"{masked_local}@{domain}"


# ---------------------------------------------------------------------------
# Display helpers (safe for WhatsApp messages)
# ---------------------------------------------------------------------------

def mask_gstin_display(gstin: str) -> str:
    """Return a partially masked GSTIN safe for WhatsApp display.

    Identical to :func:`mask_gstin` -- first 2 + last 3 visible.
    """
    return mask_gstin(gstin)


def mask_pan_display(pan: str) -> str:
    """Return a partially masked PAN safe for WhatsApp display.

    Identical to :func:`mask_pan` -- first 2 + last 1 visible.
    """
    return mask_pan(pan)


# ---------------------------------------------------------------------------
# Freeform text masking (for logging)
# ---------------------------------------------------------------------------

def mask_for_log(text: str) -> str:
    """Detect and mask ALL sensitive patterns in freeform text.

    Scans for GSTINs, PANs, phone numbers, email addresses, and
    bank-account-like digit sequences and replaces each with its masked form.

    The replacement order matters: GSTINs are replaced first (they contain
    a PAN substring), then PANs, then phone numbers, emails, and finally
    long digit runs that may be bank account numbers.
    """
    if not text:
        return text or ""

    result = text

    # 1. GSTINs first (they embed a PAN)
    def _mask_gstin_match(m: re.Match) -> str:
        return mask_gstin(m.group(1))

    result = _GSTIN_RE.sub(_mask_gstin_match, result)

    # 2. Standalone PANs (not already masked as part of a GSTIN)
    def _mask_pan_match(m: re.Match) -> str:
        return mask_pan(m.group(1))

    result = _PAN_RE.sub(_mask_pan_match, result)

    # 3. Phone numbers
    def _mask_phone_match(m: re.Match) -> str:
        return mask_phone(m.group(0))

    result = _PHONE_RE.sub(_mask_phone_match, result)

    # 4. Email addresses
    def _mask_email_match(m: re.Match) -> str:
        return mask_email(m.group(0))

    result = _EMAIL_RE.sub(_mask_email_match, result)

    # 5. Long digit runs (potential bank accounts) -- 9-18 digits
    def _mask_bank_match(m: re.Match) -> str:
        return mask_bank_account(m.group(1))

    result = _BANK_ACCOUNT_RE.sub(_mask_bank_match, result)

    return result
