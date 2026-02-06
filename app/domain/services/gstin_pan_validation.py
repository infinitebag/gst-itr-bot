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
