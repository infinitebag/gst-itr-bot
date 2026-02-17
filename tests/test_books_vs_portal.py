"""Tests for books_vs_portal dataclasses (ComparisonItem, ComparisonSummary)."""

import pytest

from app.domain.services.books_vs_portal import ComparisonItem, ComparisonSummary


# ---------------------------------------------------------------------------
# test_comparison_item_to_dict
# ---------------------------------------------------------------------------

def test_comparison_item_to_dict():
    item = ComparisonItem(
        invoice_number="INV-001",
        supplier_or_recipient_gstin="29AABCT1332L1ZM",
        books_taxable=10000.0,
        books_igst=1800.0,
        portal_taxable=10000.0,
        portal_igst=1800.0,
        status="matched",
        difference=0.0,
    )
    d = item.to_dict()

    assert d["invoice_number"] == "INV-001"
    assert d["gstin"] == "29AABCT1332L1ZM"
    assert d["books_taxable"] == 10000.0
    assert d["portal_taxable"] == 10000.0
    assert d["status"] == "matched"
    assert d["difference"] == 0.0
    # to_dict should only expose the summary keys, not all fields
    assert "books_igst" not in d
    assert "portal_igst" not in d


# ---------------------------------------------------------------------------
# test_comparison_summary_to_dict
# ---------------------------------------------------------------------------

def test_comparison_summary_to_dict():
    matched = ComparisonItem(
        invoice_number="INV-001",
        supplier_or_recipient_gstin="29AABCT1332L1ZM",
        books_taxable=5000.0,
        portal_taxable=5000.0,
        status="matched",
        difference=0.0,
    )
    mismatch = ComparisonItem(
        invoice_number="INV-002",
        supplier_or_recipient_gstin="27AAECR4582J1Z6",
        books_taxable=8000.0,
        portal_taxable=7500.0,
        status="value_mismatch",
        difference=500.0,
    )
    summary = ComparisonSummary(
        comparison_type="purchases",
        period="2024-11",
        total_books_count=2,
        total_portal_count=2,
        matched_count=1,
        value_mismatch_count=1,
        total_books_value=13000.0,
        total_portal_value=12500.0,
        net_difference=500.0,
        items=[matched, mismatch],
    )
    d = summary.to_dict()

    assert d["comparison_type"] == "purchases"
    assert d["period"] == "2024-11"
    assert d["total_books_count"] == 2
    assert d["total_portal_count"] == 2
    assert d["matched"] == 1
    assert d["value_mismatches"] == 1
    assert d["missing_in_portal"] == 0
    assert d["missing_in_books"] == 0
    assert d["books_value"] == 13000.0
    assert d["portal_value"] == 12500.0
    assert d["net_difference"] == 500.0
    # Only mismatched items should appear in the list
    assert len(d["mismatched_items"]) == 1
    assert d["mismatched_items"][0]["invoice_number"] == "INV-002"


# ---------------------------------------------------------------------------
# test_format_whatsapp_sales
# ---------------------------------------------------------------------------

def test_format_whatsapp_sales():
    summary = ComparisonSummary(
        comparison_type="sales",
        period="2024-12",
        total_books_count=10,
        total_portal_count=10,
        matched_count=10,
        total_books_value=100000.0,
        total_portal_value=100000.0,
        net_difference=0.0,
    )
    text = summary.format_whatsapp()

    assert "Sales (GSTR-1)" in text
    assert "2024-12" in text
    assert "10 invoices" in text
    assert "Matched: 10" in text
    # No mismatches, so these lines should be absent
    assert "Value mismatches" not in text
    assert "Missing in portal" not in text
    assert "Missing in books" not in text
    # Net difference is 0 so the line should not appear
    assert "Net difference" not in text


# ---------------------------------------------------------------------------
# test_format_whatsapp_purchases_with_mismatches
# ---------------------------------------------------------------------------

def test_format_whatsapp_purchases_with_mismatches():
    summary = ComparisonSummary(
        comparison_type="purchases",
        period="2024-11",
        total_books_count=15,
        total_portal_count=12,
        matched_count=8,
        value_mismatch_count=2,
        missing_in_portal_count=5,
        missing_in_books_count=2,
        total_books_value=200000.0,
        total_portal_value=180000.0,
        net_difference=20000.0,
    )
    text = summary.format_whatsapp()

    assert "Purchases (GSTR-2B)" in text
    assert "2024-11" in text
    assert "15 invoices" in text
    assert "12 invoices" in text
    assert "Matched: 8" in text
    assert "Value mismatches: 2" in text
    assert "Missing in portal: 5" in text
    assert "Missing in books: 2" in text
    assert "Net difference" in text
    assert "20,000.00" in text


# ---------------------------------------------------------------------------
# test_comparison_summary_empty
# ---------------------------------------------------------------------------

def test_comparison_summary_empty():
    summary = ComparisonSummary(
        comparison_type="sales",
        period="2025-01",
    )
    d = summary.to_dict()

    assert d["total_books_count"] == 0
    assert d["total_portal_count"] == 0
    assert d["matched"] == 0
    assert d["value_mismatches"] == 0
    assert d["missing_in_portal"] == 0
    assert d["missing_in_books"] == 0
    assert d["books_value"] == 0
    assert d["portal_value"] == 0
    assert d["net_difference"] == 0
    assert d["mismatched_items"] == []

    # WhatsApp format should still render cleanly
    text = summary.format_whatsapp()
    assert "0 invoices" in text
    assert "Matched: 0" in text
    assert "Net difference" not in text


# ---------------------------------------------------------------------------
# test_comparison_item_statuses
# ---------------------------------------------------------------------------

def test_comparison_item_statuses():
    statuses = ["matched", "value_mismatch", "missing_in_portal", "missing_in_books"]

    for status in statuses:
        item = ComparisonItem(
            invoice_number=f"INV-{status}",
            supplier_or_recipient_gstin="07AAACP0165G1ZP",
            status=status,
        )
        d = item.to_dict()
        assert d["status"] == status
        assert d["invoice_number"] == f"INV-{status}"
        assert d["gstin"] == "07AAACP0165G1ZP"

    # Verify that only non-matched items appear in summary's mismatched_items
    items = [
        ComparisonItem(invoice_number="A", supplier_or_recipient_gstin="G1", status="matched"),
        ComparisonItem(invoice_number="B", supplier_or_recipient_gstin="G2", status="value_mismatch"),
        ComparisonItem(invoice_number="C", supplier_or_recipient_gstin="G3", status="missing_in_portal"),
        ComparisonItem(invoice_number="D", supplier_or_recipient_gstin="G4", status="missing_in_books"),
    ]
    summary = ComparisonSummary(
        comparison_type="purchases",
        period="2025-01",
        items=items,
    )
    mismatched = summary.to_dict()["mismatched_items"]
    assert len(mismatched) == 3
    mismatched_inv = [m["invoice_number"] for m in mismatched]
    assert "A" not in mismatched_inv
    assert "B" in mismatched_inv
    assert "C" in mismatched_inv
    assert "D" in mismatched_inv
