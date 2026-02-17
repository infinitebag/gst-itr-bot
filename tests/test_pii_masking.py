"""Tests for PII masking utilities."""

import pytest

from app.domain.services.pii_masking import (
    MASK_CHAR,
    mask_gstin,
    mask_pan,
    mask_phone,
    mask_bank_account,
    mask_email,
    mask_gstin_display,
    mask_pan_display,
    mask_for_log,
)

# Shorthand for the bullet mask character (•)
M = MASK_CHAR


# ---------------------------------------------------------------------------
# mask_gstin
# ---------------------------------------------------------------------------

def test_mask_gstin_valid():
    assert mask_gstin("36AABCU9603R1ZM") == f"36{M * 10}1ZM"


def test_mask_gstin_empty_or_none():
    assert mask_gstin("") == ""
    assert mask_gstin(None) == ""


def test_mask_gstin_wrong_length():
    # Too short -- returned unchanged
    assert mask_gstin("36AABCU") == "36AABCU"


# ---------------------------------------------------------------------------
# mask_pan
# ---------------------------------------------------------------------------

def test_mask_pan_valid():
    assert mask_pan("ABCDE1234K") == f"AB{M * 7}K"


def test_mask_pan_empty_or_none():
    assert mask_pan("") == ""
    assert mask_pan(None) == ""


def test_mask_pan_wrong_length():
    assert mask_pan("ABC") == "ABC"


# ---------------------------------------------------------------------------
# mask_phone
# ---------------------------------------------------------------------------

def test_mask_phone_ten_digits():
    assert mask_phone("9876543210") == f"{M * 6}3210"


def test_mask_phone_with_country_code():
    assert mask_phone("+919876543210") == f"{M * 8}3210"


def test_mask_phone_empty():
    assert mask_phone("") == ""


def test_mask_phone_short():
    assert mask_phone("123") == M * 3


# ---------------------------------------------------------------------------
# mask_bank_account
# ---------------------------------------------------------------------------

def test_mask_bank_account_valid():
    assert mask_bank_account("12345678") == f"{M * 4}5678"


def test_mask_bank_account_long():
    assert mask_bank_account("123456789012345678") == f"{M * 14}5678"


def test_mask_bank_account_empty():
    assert mask_bank_account("") == ""


# ---------------------------------------------------------------------------
# mask_email
# ---------------------------------------------------------------------------

def test_mask_email_standard():
    assert mask_email("subash.t@gmail.com") == f"su{M * 6}@gmail.com"


def test_mask_email_short_local():
    assert mask_email("ab@example.com") == "ab@example.com"


def test_mask_email_single_char_local():
    assert mask_email("a@example.com") == "a@example.com"


def test_mask_email_empty():
    assert mask_email("") == ""
    assert mask_email(None) == ""


def test_mask_email_no_at():
    assert mask_email("notanemail") == "notanemail"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def test_mask_gstin_display():
    assert mask_gstin_display("27AADCB2230M1ZP") == f"27{M * 10}1ZP"


def test_mask_pan_display():
    assert mask_pan_display("AADCB2230M") == f"AA{M * 7}M"


# ---------------------------------------------------------------------------
# mask_for_log (freeform text)
# ---------------------------------------------------------------------------

def test_mask_for_log_gstin_in_text():
    text = "User GSTIN is 36AABCU9603R1ZM, please verify."
    result = mask_for_log(text)
    assert "36AABCU9603R1ZM" not in result
    assert f"36{M * 10}1ZM" in result


def test_mask_for_log_pan_in_text():
    text = "PAN: ABCDE1234K found in document."
    result = mask_for_log(text)
    assert "ABCDE1234K" not in result
    assert f"AB{M * 7}K" in result


def test_mask_for_log_phone_in_text():
    text = "Call me at 9876543210 for details."
    result = mask_for_log(text)
    assert "9876543210" not in result
    assert f"{M * 6}3210" in result


def test_mask_for_log_email_in_text():
    text = "Contact user@company.com for more info."
    result = mask_for_log(text)
    assert "user@company.com" not in result
    assert f"us{M * 2}@company.com" in result


def test_mask_for_log_multiple_patterns():
    text = (
        "GSTIN 36AABCU9603R1ZM PAN XYZPK1234L phone 9876543210 "
        "account 50100123456789"
    )
    result = mask_for_log(text)
    # GSTIN masked
    assert f"36{M * 10}1ZM" in result
    # Standalone PAN masked
    assert f"XY{M * 7}L" in result
    # Phone masked
    assert f"{M * 6}3210" in result
    # Bank account masked
    assert f"{M * 10}6789" in result


def test_mask_for_log_empty():
    assert mask_for_log("") == ""
    assert mask_for_log(None) == ""


def test_mask_for_log_no_pii():
    text = "No sensitive data here, just a note."
    assert mask_for_log(text) == text


def test_mask_char_is_bullet():
    """Verify the mask character is the bullet (•), not asterisk."""
    assert MASK_CHAR == "\u2022"
    assert MASK_CHAR == "•"
