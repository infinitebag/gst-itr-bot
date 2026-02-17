# app/domain/services/gstin_pan_validation.py

import re

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def is_valid_pan(pan: str | None) -> bool:
    if not pan:
        return False
    pan = pan.strip().upper()
    return bool(PAN_REGEX.match(pan))


def is_valid_gstin(gstin: str | None) -> bool:
    if not gstin:
        return False
    gstin = gstin.strip().upper()
    if not GSTIN_REGEX.match(gstin):
        return False

    # Extra: check PAN part inside GSTIN
    pan_part = gstin[2:12]  # chars 3–12
    return is_valid_pan(pan_part)


# ---------------------------------------------------------------------------
# WhatsApp number helpers
# ---------------------------------------------------------------------------

_INDIAN_MOBILE_REGEX = re.compile(r"^91[6-9]\d{9}$")


def normalize_whatsapp_number(raw: str) -> str | None:
    """Normalize to WhatsApp Cloud API format: ``919876543210``.

    Strips ``+``, spaces, dashes, parentheses — keeps only digits.
    Prepends ``91`` for bare 10-digit Indian mobile numbers.

    Returns the normalised string, or ``None`` if the input cannot be
    interpreted as a valid phone number (too few digits, etc.).
    """
    if not raw or not raw.strip():
        return None

    digits = re.sub(r"[^0-9]", "", raw)

    if len(digits) == 10 and digits[0] in "6789":
        return "91" + digits  # bare Indian mobile → add country code

    if len(digits) == 11 and digits[0] == "0":
        return "91" + digits[1:]  # 09876543210 → 919876543210

    if len(digits) >= 12 and digits[:2] == "91":
        return digits  # already has country code

    if len(digits) >= 10:
        return digits  # non-Indian / full international number

    return None  # too short to be a valid phone number


def is_valid_whatsapp_number(number: str | None) -> bool:
    """Check that a *normalised* number is a valid Indian mobile.

    Expected format: ``91`` + 10-digit number starting with 6–9.
    """
    if not number:
        return False
    return bool(_INDIAN_MOBILE_REGEX.match(number))
