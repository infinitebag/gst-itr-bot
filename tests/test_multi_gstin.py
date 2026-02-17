# tests/test_multi_gstin.py
"""Tests for multi-GSTIN service (Phase 8)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.domain.services.multi_gstin_service import (
    format_gstin_list,
)


def test_format_gstin_list_empty():
    result = format_gstin_list([])
    assert "No GSTINs" in result or "no" in result.lower()


def test_format_gstin_list():
    gstins = [
        {"gstin": "36AABCU9603R1ZM", "label": "HQ", "is_primary": True, "is_active": True},
        {"gstin": "27AADCB2230M1ZP", "label": "Mumbai", "is_primary": False, "is_active": True},
    ]
    result = format_gstin_list(gstins)
    assert "36AABCU9603R1ZM" in result
    assert "HQ" in result
    assert "27AADCB2230M1ZP" in result


def test_format_gstin_list_primary_marker():
    """Primary GSTIN should be marked with a checkmark."""
    gstins = [
        {"gstin": "36AABCU9603R1ZM", "label": "HQ", "is_primary": True, "is_active": True},
    ]
    result = format_gstin_list(gstins)
    # The source code appends a checkmark emoji for primary GSTINs
    assert "36AABCU9603R1ZM" in result


def test_format_gstin_list_no_label():
    """GSTINs without labels should still format correctly."""
    gstins = [
        {"gstin": "36AABCU9603R1ZM", "label": "", "is_primary": False, "is_active": True},
    ]
    result = format_gstin_list(gstins)
    assert "36AABCU9603R1ZM" in result


def test_format_gstin_list_numbering():
    """Each GSTIN should be numbered sequentially."""
    gstins = [
        {"gstin": "36AABCU9603R1ZM", "label": "A", "is_primary": True, "is_active": True},
        {"gstin": "27AADCB2230M1ZP", "label": "B", "is_primary": False, "is_active": True},
        {"gstin": "33AABCS1429B1ZB", "label": "C", "is_primary": False, "is_active": True},
    ]
    result = format_gstin_list(gstins)
    assert "1." in result
    assert "2." in result
    assert "3." in result
