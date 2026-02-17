# tests/test_gst_filing.py
"""
Tests for GST filing infrastructure:
- gst_export.py (JSON builders)
- mastergst_client.py (client structure)
- gst_service.py (NIL filing)
"""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.models.gst import (
    Gstr3bSummary,
    ItcBucket,
    TaxBucket,
)
from app.domain.services.gst_export import make_gstr3b_json, make_gstr1_json
from app.domain.services.gst_service import (
    prepare_gstr3b,
    prepare_nil_gstr3b,
    prepare_nil_gstr1,
    get_current_gst_period,
)
from app.domain.services.gstr1_service import (
    Gstr1B2BEntry,
    Gstr1B2CInvoice,
    Gstr1Invoice,
    Gstr1Item,
    Gstr1Payload,
)
from app.infrastructure.external.mastergst_client import MasterGSTClient, MasterGSTError


# ============================================================
# gst_export.py — make_gstr3b_json
# ============================================================

class TestMakeGstr3bJson:
    """Tests for GSTR-3B JSON builder."""

    def test_basic_gstr3b_json(self):
        """make_gstr3b_json produces correct structure from Gstr3bSummary."""
        summary = Gstr3bSummary(
            outward_taxable_supplies=TaxBucket(
                taxable_value=Decimal("100000"),
                igst=Decimal("0"),
                cgst=Decimal("9000"),
                sgst=Decimal("9000"),
                cess=Decimal("0"),
            ),
            inward_reverse_charge=TaxBucket(),
            itc_eligible=ItcBucket(
                igst=Decimal("0"),
                cgst=Decimal("9000"),
                sgst=Decimal("9000"),
                cess=Decimal("0"),
            ),
        )

        result = make_gstr3b_json("36AABCU9603R1ZM", date(2025, 1, 1), summary)

        assert result["gstin"] == "36AABCU9603R1ZM"
        assert result["fp"] == "012025"
        assert result["sup_details"]["osup_det"]["txval"] == 100000.0
        assert result["sup_details"]["osup_det"]["cgst"] == 9000.0
        assert result["sup_details"]["osup_det"]["sgst"] == 9000.0
        assert result["itc_elg"]["itc_net"]["cgst"] == 9000.0

    def test_gstr3b_json_with_rcm(self):
        """GSTR-3B JSON includes reverse charge details."""
        summary = Gstr3bSummary(
            outward_taxable_supplies=TaxBucket(
                taxable_value=Decimal("50000"),
                igst=Decimal("9000"),
            ),
            inward_reverse_charge=TaxBucket(
                taxable_value=Decimal("10000"),
                igst=Decimal("1800"),
            ),
            itc_eligible=ItcBucket(igst=Decimal("1800")),
        )

        result = make_gstr3b_json("27AADCB2230M1ZP", date(2025, 3, 1), summary)

        assert result["fp"] == "032025"
        assert result["sup_details"]["isup_rev"]["txval"] == 10000.0
        assert result["sup_details"]["isup_rev"]["igst"] == 1800.0

    def test_gstr3b_json_nil_summary(self):
        """NIL summary produces all-zero JSON."""
        summary = Gstr3bSummary()
        result = make_gstr3b_json("36AABCU9603R1ZM", date(2025, 1, 1), summary)

        assert result["sup_details"]["osup_det"]["txval"] == 0.0
        assert result["sup_details"]["osup_det"]["igst"] == 0.0
        assert result["itc_elg"]["itc_net"]["igst"] == 0.0

    def test_gstr3b_json_has_required_sections(self):
        """GSTR-3B JSON has all required top-level sections."""
        summary = Gstr3bSummary()
        result = make_gstr3b_json("36AABCU9603R1ZM", date(2025, 1, 1), summary)

        assert "gstin" in result
        assert "fp" in result
        assert "sup_details" in result
        assert "itc_elg" in result
        assert "inward_sup" in result
        assert "intr_ltfee" in result

    def test_gstr3b_period_formatting(self):
        """Filing period formats as MMYYYY correctly for various months."""
        summary = Gstr3bSummary()

        # January
        result = make_gstr3b_json("X", date(2025, 1, 1), summary)
        assert result["fp"] == "012025"

        # December
        result = make_gstr3b_json("X", date(2025, 12, 1), summary)
        assert result["fp"] == "122025"

        # Single-digit month
        result = make_gstr3b_json("X", date(2025, 6, 1), summary)
        assert result["fp"] == "062025"


# ============================================================
# gst_export.py — make_gstr1_json
# ============================================================

class TestMakeGstr1Json:
    """Tests for GSTR-1 JSON builder."""

    def _make_payload(self) -> Gstr1Payload:
        """Create a sample GSTR-1 payload."""
        item = Gstr1Item(
            txval=Decimal("50000"),
            rt=Decimal("18"),
            igst=Decimal("9000"),
            cgst=Decimal("0"),
            sgst=Decimal("0"),
        )
        inv = Gstr1Invoice(
            num="INV-001",
            dt="01-01-2025",
            val=Decimal("59000"),
            pos="27",
            itms=[item],
        )
        b2b = Gstr1B2BEntry(ctin="27AADCB2230M1ZP", inv=[inv])

        b2c = Gstr1B2CInvoice(
            pos="36",
            txval=Decimal("20000"),
            rt=Decimal("18"),
            igst=Decimal("0"),
            cgst=Decimal("1800"),
            sgst=Decimal("1800"),
        )

        return Gstr1Payload(
            gstin="36AABCU9603R1ZM",
            fp="012025",
            b2b=[b2b],
            b2c=[b2c],
        )

    def test_gstr1_json_structure(self):
        """make_gstr1_json produces correct top-level structure."""
        payload = self._make_payload()
        result = make_gstr1_json(payload)

        assert result["gstin"] == "36AABCU9603R1ZM"
        assert result["fp"] == "012025"
        assert "b2b" in result
        assert "b2cs" in result
        assert len(result["b2b"]) == 1
        assert len(result["b2cs"]) == 1

    def test_gstr1_b2b_serialization(self):
        """B2B entries are serialized correctly."""
        payload = self._make_payload()
        result = make_gstr1_json(payload)

        b2b = result["b2b"][0]
        assert b2b["ctin"] == "27AADCB2230M1ZP"
        assert len(b2b["inv"]) == 1

        inv = b2b["inv"][0]
        assert inv["inum"] == "INV-001"
        assert inv["val"] == 59000.0
        assert inv["pos"] == "27"
        assert inv["itms"][0]["itm_det"]["txval"] == 50000.0
        assert inv["itms"][0]["itm_det"]["rt"] == 18.0
        assert inv["itms"][0]["itm_det"]["iamt"] == 9000.0

    def test_gstr1_b2c_serialization(self):
        """B2C entries are serialized correctly."""
        payload = self._make_payload()
        result = make_gstr1_json(payload)

        b2c = result["b2cs"][0]
        assert b2c["pos"] == "36"
        assert b2c["txval"] == 20000.0
        assert b2c["camt"] == 1800.0
        assert b2c["samt"] == 1800.0

    def test_gstr1_grand_total(self):
        """Grand total includes both B2B and B2C values."""
        payload = self._make_payload()
        result = make_gstr1_json(payload)

        # B2B invoice val=59000, B2C txval=20000
        assert result["gt"] == 79000.0

    def test_gstr1_empty_payload(self):
        """Empty payload produces valid JSON with empty arrays."""
        payload = Gstr1Payload(gstin="X", fp="012025", b2b=[], b2c=[])
        result = make_gstr1_json(payload)

        assert result["b2b"] == []
        assert result["b2cs"] == []
        assert result["gt"] == 0.0

    def test_gstr1_has_all_sections(self):
        """GSTR-1 JSON has all required sections."""
        payload = Gstr1Payload(gstin="X", fp="012025")
        result = make_gstr1_json(payload)

        for key in ["b2b", "b2cs", "b2cl", "cdnr", "cdnur", "exp", "nil", "hsn", "doc_issue"]:
            assert key in result, f"Missing key: {key}"


# ============================================================
# gst_service.py — prepare_gstr3b
# ============================================================

class TestPrepareGstr3b:
    """Tests for GSTR-3B summary preparation from invoices."""

    def test_prepare_from_invoices(self):
        """prepare_gstr3b correctly aggregates invoice data."""
        invoices = [
            {
                "taxable_value": 50000,
                "igst_amount": 0,
                "cgst_amount": 4500,
                "sgst_amount": 4500,
            },
            {
                "taxable_value": 30000,
                "igst_amount": 5400,
                "cgst_amount": 0,
                "sgst_amount": 0,
            },
        ]
        summary = prepare_gstr3b(invoices)

        assert summary.outward_taxable_supplies.taxable_value == Decimal("80000")
        assert summary.outward_taxable_supplies.cgst == Decimal("4500")
        assert summary.outward_taxable_supplies.igst == Decimal("5400")

    def test_prepare_with_rcm(self):
        """Reverse charge invoices go to inward_reverse_charge."""
        invoices = [
            {
                "taxable_value": 10000,
                "igst_amount": 1800,
                "reverse_charge": True,
            },
        ]
        summary = prepare_gstr3b(invoices)

        assert summary.inward_reverse_charge.taxable_value == Decimal("10000")
        assert summary.inward_reverse_charge.igst == Decimal("1800")
        assert summary.outward_taxable_supplies.taxable_value == Decimal("0")

    def test_prepare_with_itc(self):
        """ITC-eligible invoices contribute to itc_eligible bucket."""
        invoices = [
            {
                "taxable_value": 25000,
                "cgst_amount": 2250,
                "sgst_amount": 2250,
                "itc_eligible": True,
            },
        ]
        summary = prepare_gstr3b(invoices)

        assert summary.itc_eligible.cgst == Decimal("2250")
        assert summary.itc_eligible.sgst == Decimal("2250")

    def test_prepare_demo_mode(self):
        """Demo mode returns realistic dummy data."""
        summary = prepare_gstr3b(None, demo=True)

        assert summary.outward_taxable_supplies.taxable_value > 0
        assert summary.itc_eligible.cgst > 0

    def test_prepare_empty_invoices(self):
        """Empty invoice list returns demo summary."""
        summary = prepare_gstr3b([])

        # Empty list triggers demo mode
        assert summary.outward_taxable_supplies.taxable_value > 0


# ============================================================
# gst_service.py — NIL Filing
# ============================================================

class TestNilFiling:
    """Tests for NIL filing preparation."""

    def test_nil_gstr3b_success(self):
        """prepare_nil_gstr3b returns valid NilFilingResult."""
        result = prepare_nil_gstr3b("36AABCU9603R1ZM", "2025-01")

        assert result.form_type == "GSTR-3B"
        assert result.gstin == "36AABCU9603R1ZM"
        assert result.period == "2025-01"
        assert result.status == "success"
        assert result.reference_number.startswith("NIL3B")
        assert len(result.message) > 0

    def test_nil_gstr1_success(self):
        """prepare_nil_gstr1 returns valid NilFilingResult."""
        result = prepare_nil_gstr1("36AABCU9603R1ZM", "2025-01")

        assert result.form_type == "GSTR-1"
        assert result.status == "success"
        assert result.reference_number.startswith("NIL1")

    def test_nil_deterministic_reference(self):
        """Same inputs produce same reference number on same day."""
        r1 = prepare_nil_gstr3b("36AABCU9603R1ZM", "2025-01")
        r2 = prepare_nil_gstr3b("36AABCU9603R1ZM", "2025-01")

        assert r1.reference_number == r2.reference_number


# ============================================================
# gst_service.py — get_current_gst_period
# ============================================================

class TestGetCurrentGstPeriod:
    """Tests for GST period calculation."""

    def test_period_format(self):
        """Period is YYYY-MM format."""
        period = get_current_gst_period()
        assert len(period) == 7
        assert period[4] == "-"
        year, month = period.split("-")
        assert int(year) >= 2024
        assert 1 <= int(month) <= 12


# ============================================================
# mastergst_client.py — MasterGSTClient construction
# ============================================================

class TestMasterGSTClientInit:
    """Tests for MasterGST client initialization."""

    def test_client_creation(self):
        """Client can be instantiated."""
        client = MasterGSTClient()
        assert client.base is not None
        assert isinstance(client.base, str)

    def test_common_headers_building(self):
        """_common_headers builds correct header dict."""
        client = MasterGSTClient()
        headers = client._common_headers()

        assert headers["Content-Type"] == "application/json"
        assert "client_id" in headers
        assert "client_secret" in headers
        assert "ip_address" in headers

    def test_auth_headers_with_token(self):
        """_auth_headers includes gstin and auth-token."""
        client = MasterGSTClient()
        headers = client._auth_headers("36AABCU9603R1ZM", auth_token="test-token")

        assert headers["gstin"] == "36AABCU9603R1ZM"
        assert headers["auth-token"] == "test-token"
        assert headers["Content-Type"] == "application/json"

    def test_mastergst_error(self):
        """MasterGSTError carries status_code and response."""
        err = MasterGSTError("test error", status_code=400, response={"detail": "bad"})
        assert str(err) == "test error"
        assert err.status_code == 400
        assert err.response["detail"] == "bad"

    def test_mastergst_error_defaults(self):
        """MasterGSTError has safe defaults."""
        err = MasterGSTError("simple error")
        assert err.status_code == 0
        assert err.response == {}
