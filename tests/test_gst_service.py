"""Tests for GST service."""

from decimal import Decimal

from app.domain.services.gst_service import (
    prepare_gstr3b,
    prepare_nil_gstr3b,
    prepare_nil_gstr1,
    get_current_gst_period,
)


class TestGSTR3BPreparation:
    """Test GSTR-3B summary preparation."""

    def test_demo_mode(self):
        result = prepare_gstr3b(demo=True)
        assert result.outward_taxable_supplies.taxable_value > 0

    def test_empty_invoices(self):
        result = prepare_gstr3b(invoices=[])
        # Should return demo data when no invoices
        assert result.outward_taxable_supplies is not None

    def test_basic_invoice_aggregation(self):
        invoices = [
            {
                "taxable_value": 10000,
                "igst_amount": 0,
                "cgst_amount": 900,
                "sgst_amount": 900,
                "cess_amount": 0,
                "reverse_charge": False,
                "itc_eligible": True,
            },
            {
                "taxable_value": 20000,
                "igst_amount": 3600,
                "cgst_amount": 0,
                "sgst_amount": 0,
                "cess_amount": 0,
                "reverse_charge": False,
                "itc_eligible": True,
            },
        ]
        result = prepare_gstr3b(invoices=invoices)
        assert result.outward_taxable_supplies.taxable_value == Decimal("30000")
        assert result.outward_taxable_supplies.cgst == Decimal("900")
        assert result.outward_taxable_supplies.igst == Decimal("3600")

    def test_reverse_charge_segregation(self):
        invoices = [
            {
                "taxable_value": 5000,
                "igst_amount": 900,
                "cgst_amount": 0,
                "sgst_amount": 0,
                "cess_amount": 0,
                "reverse_charge": True,
                "itc_eligible": True,
            },
        ]
        result = prepare_gstr3b(invoices=invoices)
        assert result.inward_reverse_charge.taxable_value == Decimal("5000")
        assert result.outward_taxable_supplies.taxable_value == Decimal("0")

    def test_itc_default_false(self):
        """ITC should default to False (conservative) when not specified."""
        invoices = [
            {
                "taxable_value": 10000,
                "igst_amount": 1800,
                "cgst_amount": 0,
                "sgst_amount": 0,
                "cess_amount": 0,
            },
        ]
        result = prepare_gstr3b(invoices=invoices)
        # ITC should be 0 since itc_eligible defaults to False
        assert result.itc_eligible.igst == Decimal("0")


class TestNILFiling:
    """Test NIL return preparation."""

    def test_nil_gstr3b(self):
        result = prepare_nil_gstr3b("22AAAAA0000A1Z5", "2025-01")
        assert result.form_type == "GSTR-3B"
        assert result.status == "success"
        assert result.reference_number.startswith("NIL3B")

    def test_nil_gstr1(self):
        result = prepare_nil_gstr1("22AAAAA0000A1Z5", "2025-01")
        assert result.form_type == "GSTR-1"
        assert result.status == "success"
        assert result.reference_number.startswith("NIL1")


class TestGSTPeriod:
    """Test GST period calculation."""

    def test_period_format(self):
        period = get_current_gst_period()
        # Should be YYYY-MM format
        assert len(period) == 7
        assert "-" in period
