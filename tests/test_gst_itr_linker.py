"""Tests for the GST-to-ITR linker."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.services.gst_itr_linker import (
    GSTLinkResult,
    ay_to_fy,
    fy_to_date_range,
    get_gst_data_from_session,
    gst_link_to_dict,
    dict_to_gst_link,
    _safe_decimal,
    _parse_invoice_date,
)


# ---------------------------------------------------------------------------
# ay_to_fy tests
# ---------------------------------------------------------------------------

class TestAYtoFY:

    def test_standard_conversion(self):
        assert ay_to_fy("2025-26") == "2024-26"

    def test_another_year(self):
        assert ay_to_fy("2024-25") == "2023-25"

    def test_passthrough_if_invalid(self):
        # If format is unexpected, return as-is
        result = ay_to_fy("2025")
        assert result == "2025"


# ---------------------------------------------------------------------------
# fy_to_date_range tests
# ---------------------------------------------------------------------------

class TestFYtoDateRange:

    def test_standard_range(self):
        start, end = fy_to_date_range("2024-25")
        assert start == date(2024, 4, 1)
        assert end == date(2025, 3, 31)

    def test_another_year(self):
        start, end = fy_to_date_range("2023-24")
        assert start == date(2023, 4, 1)
        assert end == date(2024, 3, 31)


# ---------------------------------------------------------------------------
# _safe_decimal tests
# ---------------------------------------------------------------------------

class TestSafeDecimal:

    def test_integer(self):
        assert _safe_decimal(100) == Decimal("100")

    def test_float(self):
        assert _safe_decimal(99.5) == Decimal("99.5")

    def test_string(self):
        assert _safe_decimal("12345.67") == Decimal("12345.67")

    def test_none(self):
        assert _safe_decimal(None) == Decimal("0")

    def test_invalid_string(self):
        assert _safe_decimal("not-a-number") == Decimal("0")

    def test_zero(self):
        assert _safe_decimal(0) == Decimal("0")

    def test_decimal_input(self):
        assert _safe_decimal(Decimal("500")) == Decimal("500")


# ---------------------------------------------------------------------------
# _parse_invoice_date tests
# ---------------------------------------------------------------------------

class TestParseInvoiceDate:

    def test_none(self):
        assert _parse_invoice_date(None) is None

    def test_date_object(self):
        d = date(2024, 7, 15)
        assert _parse_invoice_date(d) == d

    def test_datetime_object(self):
        dt = datetime(2024, 7, 15, 10, 30)
        result = _parse_invoice_date(dt)
        # datetime is a subclass of date, so isinstance check matches date first
        # The function returns the original datetime (which compares equal by date fields)
        assert result.year == 2024
        assert result.month == 7
        assert result.day == 15

    def test_iso_format(self):
        assert _parse_invoice_date("2024-07-15") == date(2024, 7, 15)

    def test_dd_mm_yyyy_dash(self):
        assert _parse_invoice_date("15-07-2024") == date(2024, 7, 15)

    def test_dd_mm_yyyy_slash(self):
        assert _parse_invoice_date("15/07/2024") == date(2024, 7, 15)

    def test_yyyy_mm_dd_slash(self):
        assert _parse_invoice_date("2024/07/15") == date(2024, 7, 15)

    def test_invalid_string(self):
        assert _parse_invoice_date("not-a-date") is None

    def test_empty_string(self):
        assert _parse_invoice_date("") is None


# ---------------------------------------------------------------------------
# get_gst_data_from_session tests
# ---------------------------------------------------------------------------

class TestGetGSTDataFromSession:

    def test_empty_session(self):
        assert get_gst_data_from_session({}) is None

    def test_no_invoices(self):
        session = {"data": {"uploaded_invoices": []}}
        assert get_gst_data_from_session(session) is None

    def test_invoices_in_fy(self):
        session = {
            "data": {
                "uploaded_invoices": [
                    {
                        "invoice_date": "2024-06-15",
                        "taxable_value": 100000,
                        "tax_amount": 18000,
                    },
                    {
                        "invoice_date": "2024-09-20",
                        "taxable_value": 200000,
                        "tax_amount": 36000,
                    },
                ],
                "gst_filings": [],
            }
        }
        result = get_gst_data_from_session(session, "2025-26")
        assert result is not None
        assert result.total_turnover == Decimal("300000")
        assert result.total_tax_collected == Decimal("54000")
        assert result.invoice_count == 2
        assert "2024-06" in result.period_coverage
        assert "2024-09" in result.period_coverage

    def test_invoices_outside_fy_excluded(self):
        session = {
            "data": {
                "uploaded_invoices": [
                    {
                        "invoice_date": "2023-06-15",
                        "taxable_value": 100000,
                        "tax_amount": 18000,
                    },
                ],
            }
        }
        result = get_gst_data_from_session(session, "2025-26")
        assert result is None

    def test_invoices_without_date_included(self):
        session = {
            "data": {
                "uploaded_invoices": [
                    {
                        "taxable_value": 50000,
                        "tax_amount": 9000,
                    },
                ],
            }
        }
        result = get_gst_data_from_session(session, "2025-26")
        assert result is not None
        assert result.total_turnover == Decimal("50000")
        assert result.invoice_count == 1

    def test_smart_invoices_included(self):
        session = {
            "data": {
                "uploaded_invoices": [],
                "smart_invoices": [
                    {
                        "invoice_date": "2024-08-01",
                        "taxable_value": 75000,
                        "tax_amount": 13500,
                    },
                ],
            }
        }
        result = get_gst_data_from_session(session, "2025-26")
        assert result is not None
        assert result.total_turnover == Decimal("75000")

    def test_filing_references_collected(self):
        session = {
            "data": {
                "uploaded_invoices": [
                    {"taxable_value": 10000, "tax_amount": 1800},
                ],
                "gst_filings": [
                    {
                        "form_type": "GSTR-3B",
                        "period": "2024-07",
                        "reference_number": "REF123",
                        "status": "filed",
                    },
                ],
            }
        }
        result = get_gst_data_from_session(session, "2025-26")
        assert result is not None
        assert len(result.filing_references) == 1
        assert result.filing_references[0]["form_type"] == "GSTR-3B"

    def test_missing_tax_amount(self):
        session = {
            "data": {
                "uploaded_invoices": [
                    {"invoice_date": "2024-06-15", "taxable_value": 100000},
                ],
            }
        }
        result = get_gst_data_from_session(session, "2025-26")
        assert result is not None
        assert result.total_tax_collected == Decimal("0")


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------

class TestGSTLinkSerialization:

    def test_roundtrip(self):
        original = GSTLinkResult(
            total_turnover=Decimal("500000"),
            total_tax_collected=Decimal("90000"),
            invoice_count=5,
            filing_references=[{"form_type": "GSTR-3B", "period": "2024-07"}],
            period_coverage=["2024-04", "2024-07"],
        )
        d = gst_link_to_dict(original)
        restored = dict_to_gst_link(d)
        assert restored.total_turnover == Decimal("500000")
        assert restored.total_tax_collected == Decimal("90000")
        assert restored.invoice_count == 5
        assert len(restored.filing_references) == 1
        assert restored.period_coverage == ["2024-04", "2024-07"]

    def test_dict_to_gst_link_empty(self):
        result = dict_to_gst_link({})
        assert result.total_turnover == Decimal("0")
        assert result.invoice_count == 0

    def test_dict_to_gst_link_none(self):
        result = dict_to_gst_link(None)
        assert result.total_turnover == Decimal("0")

    def test_gst_link_to_dict_values_are_strings(self):
        original = GSTLinkResult(total_turnover=Decimal("123456.78"))
        d = gst_link_to_dict(original)
        assert d["total_turnover"] == "123456.78"
        assert isinstance(d["total_turnover"], str)
