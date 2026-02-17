"""Tests for invoice parser."""

from app.domain.services.invoice_parser import parse_invoice_text


class TestInvoiceParser:
    """Test heuristic invoice text parser."""

    def test_empty_text(self):
        result = parse_invoice_text("")
        assert result.supplier_gstin is None

    def test_extracts_gstin(self, sample_invoice_text):
        result = parse_invoice_text(sample_invoice_text)
        assert result.supplier_gstin == "36AABCU9603R1ZM"
        assert result.receiver_gstin == "27AADCB2230M1ZP"

    def test_extracts_invoice_number(self, sample_invoice_text):
        result = parse_invoice_text(sample_invoice_text)
        assert result.invoice_number is not None
        # Parser may lowercase the invoice number
        assert "inv-2025-001" in result.invoice_number.lower()

    def test_extracts_date(self, sample_invoice_text):
        result = parse_invoice_text(sample_invoice_text)
        assert result.invoice_date is not None
        assert result.invoice_date.day == 15
        assert result.invoice_date.month == 1
        assert result.invoice_date.year == 2025

    def test_extracts_igst(self, sample_invoice_text):
        result = parse_invoice_text(sample_invoice_text)
        assert result.igst_amount is not None
        assert result.igst_amount == 15300.0

    def test_extracts_total_amount(self, sample_invoice_text):
        result = parse_invoice_text(sample_invoice_text)
        assert result.total_amount is not None

    def test_extracts_hsn_code(self, sample_invoice_text):
        result = parse_invoice_text(sample_invoice_text)
        assert result.hsn_code == "84715000"

    def test_extracts_place_of_supply(self, sample_invoice_text):
        result = parse_invoice_text(sample_invoice_text)
        assert result.place_of_supply is not None
        assert "27" in result.place_of_supply or "Maharashtra" in result.place_of_supply


class TestCGSTSGSTExtraction:
    """Test CGST/SGST extraction from intra-state invoices."""

    def test_cgst_sgst_extraction(self):
        text = """
        Tax Invoice
        Invoice No: INV-100
        Date: 10/02/2025
        Supplier GSTIN: 36AABCU9603R1ZM
        Taxable Value: Rs 50,000.00
        CGST @ 9%: Rs 4,500.00
        SGST @ 9%: Rs 4,500.00
        Total: Rs 59,000.00
        """
        result = parse_invoice_text(text)
        assert result.cgst_amount == 4500.0
        assert result.sgst_amount == 4500.0
        assert result.tax_amount == 9000.0
