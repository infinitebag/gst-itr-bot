"""Tests for the pending ITC service — dataclasses and vendor follow-up."""

import asyncio

import pytest

from app.domain.services.pending_itc_service import (
    PendingITCItem,
    PendingITCSummary,
    generate_vendor_followup_message,
)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _make_item(**overrides) -> PendingITCItem:
    defaults = {
        "supplier_gstin": "29AABCU9603R1ZM",
        "invoice_number": "INV-001",
        "invoice_date": "2025-01-15",
        "taxable_value": 10000.0,
        "igst": 1800.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "total_itc": 1800.0,
        "periods_pending": 1,
        "original_period": "2025-01",
    }
    defaults.update(overrides)
    return PendingITCItem(**defaults)


class TestPendingITCSummaryEmpty:

    def test_pending_itc_summary_empty(self):
        """An empty PendingITCSummary has zero totals and no items."""
        summary = PendingITCSummary()
        assert summary.total_pending_itc == 0
        assert summary.pending_count == 0
        assert summary.suppliers_affected == 0
        assert summary.items == []
        assert summary.aged_buckets == {}


class TestVendorFollowup:

    def test_generate_vendor_followup_english(self):
        """English follow-up message contains supplier GSTIN and invoice number."""
        item = _make_item()
        msg = generate_vendor_followup_message(item, business_name="TestCorp", lang="en")
        assert "29AABCU9603R1ZM" in msg
        assert "INV-001" in msg
        assert "TestCorp" in msg
        assert "GSTR-2B" in msg
        assert "GSTR-1" in msg
        assert "10,000.00" in msg

    def test_generate_vendor_followup_hindi(self):
        """Hindi follow-up message contains supplier GSTIN and invoice number."""
        item = _make_item()
        msg = generate_vendor_followup_message(item, lang="hi")
        assert "29AABCU9603R1ZM" in msg
        assert "INV-001" in msg
        assert "GSTR-2B" in msg
        assert "GSTR-1" in msg
        assert "10,000.00" in msg


class TestPendingITCItemToDict:

    def test_pending_itc_item_to_dict(self):
        """to_dict returns the expected keys and values."""
        item = _make_item(
            supplier_gstin="07AAACN0266B1Z5",
            invoice_number="INV-999",
            taxable_value=50000.0,
            total_itc=9000.0,
            periods_pending=3,
            original_period="2024-10",
        )
        d = item.to_dict()
        assert d["supplier_gstin"] == "07AAACN0266B1Z5"
        assert d["invoice_number"] == "INV-999"
        assert d["taxable_value"] == 50000.0
        assert d["total_itc"] == 9000.0
        assert d["periods_pending"] == 3
        assert d["original_period"] == "2024-10"
        assert "invoice_date" in d


class TestPendingITCSummaryToDict:

    def test_pending_itc_summary_to_dict(self):
        """to_dict nests item dicts and includes aggregate fields."""
        item_a = _make_item(supplier_gstin="29AABCU9603R1ZM", total_itc=1800.0)
        item_b = _make_item(supplier_gstin="07AAACN0266B1Z5", total_itc=3600.0)

        summary = PendingITCSummary(
            total_pending_itc=5400.0,
            pending_count=2,
            suppliers_affected=2,
            items=[item_a, item_b],
            aged_buckets={"1_month": 2, "2_3_months": 0, "3_plus_months": 0},
        )
        d = summary.to_dict()
        assert d["total_pending_itc"] == 5400.0
        assert d["pending_count"] == 2
        assert d["suppliers_affected"] == 2
        assert len(d["items"]) == 2
        assert d["items"][0]["supplier_gstin"] == "29AABCU9603R1ZM"
        assert d["items"][1]["supplier_gstin"] == "07AAACN0266B1Z5"
        assert d["aged_buckets"]["1_month"] == 2
