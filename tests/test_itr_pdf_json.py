# tests/test_itr_pdf_json.py
"""
Tests for ITR PDF + JSON generation:
- itr_pdf.py  (generate_itr1_pdf, generate_itr4_pdf)
- itr_json.py (generate_itr1_json, generate_itr4_json, itr_json_to_string)
"""

from decimal import Decimal

import pytest

from app.domain.services.itr_service import (
    ITR1Input,
    ITR4Input,
    ITRResult,
    TaxBreakdown,
    compute_itr1,
    compute_itr4,
)
from app.domain.services.itr_json import (
    generate_itr1_json,
    generate_itr4_json,
    itr_json_to_string,
)
from app.domain.services.itr_pdf import (
    generate_itr1_pdf,
    generate_itr4_pdf,
)


# ============================================================
# Fixtures — shared input + result objects
# ============================================================

@pytest.fixture
def itr1_input() -> ITR1Input:
    return ITR1Input(
        pan="ABCDE1234F",
        name="Test User",
        assessment_year="2025-26",
        salary_income=Decimal("1000000"),
        other_income=Decimal("50000"),
        section_80c=Decimal("150000"),
        section_80d=Decimal("25000"),
        tds_total=Decimal("80000"),
    )


@pytest.fixture
def itr1_result(itr1_input: ITR1Input) -> ITRResult:
    return compute_itr1(itr1_input)


@pytest.fixture
def itr4_input() -> ITR4Input:
    return ITR4Input(
        pan="XYZAB5678C",
        name="Business User",
        assessment_year="2025-26",
        gross_turnover=Decimal("5000000"),
        presumptive_rate=Decimal("8"),
        section_80c=Decimal("100000"),
        tds_total=Decimal("30000"),
    )


@pytest.fixture
def itr4_result(itr4_input: ITR4Input) -> ITRResult:
    return compute_itr4(itr4_input)


# ============================================================
# itr_json.py — generate_itr1_json
# ============================================================

class TestGenerateItr1Json:
    """Tests for ITR-1 JSON generation."""

    def test_basic_structure(self, itr1_input, itr1_result):
        """ITR-1 JSON has required top-level keys."""
        data = generate_itr1_json(itr1_input, itr1_result)

        assert data["formType"] == "ITR-1"
        assert data["assessmentYear"] == "2025-26"
        for key in ("personalInfo", "incomeDetails", "deductions",
                     "taxComputation", "taxPayments", "verification"):
            assert key in data, f"Missing key: {key}"

    def test_personal_info(self, itr1_input, itr1_result):
        """personalInfo contains correct PAN and name."""
        data = generate_itr1_json(itr1_input, itr1_result)
        pi = data["personalInfo"]

        assert pi["pan"] == "ABCDE1234F"
        assert pi["name"] == "Test User"

    def test_income_details(self, itr1_input, itr1_result):
        """incomeDetails has correct salary, deductions, and totals."""
        data = generate_itr1_json(itr1_input, itr1_result)
        inc = data["incomeDetails"]

        assert inc["grossSalary"] == 1000000.0
        assert inc["standardDeduction"] == 75000.0
        assert inc["netSalary"] == 925000.0  # 1000000 - 75000
        assert inc["otherIncome"] == 50000.0
        assert inc["grossTotalIncome"] > 0

    def test_deductions(self, itr1_input, itr1_result):
        """deductions section includes Chapter VI-A values."""
        data = generate_itr1_json(itr1_input, itr1_result)
        ded = data["deductions"]

        assert ded["section80C"] == 150000.0
        assert ded["section80D"] == 25000.0
        assert ded["totalDeductions"] >= 0

    def test_tax_computation(self, itr1_input, itr1_result):
        """taxComputation has both regimes and recommendation."""
        data = generate_itr1_json(itr1_input, itr1_result)
        tc = data["taxComputation"]

        assert tc["recommendedRegime"] in ("old", "new")
        assert tc["savings"] >= 0
        assert "oldRegime" in tc
        assert "newRegime" in tc
        assert tc["oldRegime"]["regime"] == "old"
        assert tc["newRegime"]["regime"] == "new"

    def test_tax_payments(self, itr1_input, itr1_result):
        """taxPayments includes TDS and totals."""
        data = generate_itr1_json(itr1_input, itr1_result)
        tp = data["taxPayments"]

        assert tp["tdsTotal"] == 80000.0
        assert tp["totalPaid"] == 80000.0

    def test_verification(self, itr1_input, itr1_result):
        """verification section has timestamp and disclaimer."""
        data = generate_itr1_json(itr1_input, itr1_result)
        v = data["verification"]

        assert "generatedAt" in v
        assert "computedBy" in v
        assert "disclaimer" in v

    def test_regime_breakdown_has_all_fields(self, itr1_input, itr1_result):
        """Each regime breakdown dict has all expected keys."""
        data = generate_itr1_json(itr1_input, itr1_result)
        old = data["taxComputation"]["oldRegime"]

        expected_keys = {
            "regime", "grossTotalIncome", "totalDeductions",
            "taxableIncome", "taxOnIncome", "rebate87A",
            "surcharge", "healthCess", "totalTaxLiability",
            "taxesPaid", "taxPayable", "slabDetails",
        }
        assert set(old.keys()) == expected_keys


# ============================================================
# itr_json.py — generate_itr4_json
# ============================================================

class TestGenerateItr4Json:
    """Tests for ITR-4 JSON generation."""

    def test_basic_structure(self, itr4_input, itr4_result):
        """ITR-4 JSON has required top-level keys."""
        data = generate_itr4_json(itr4_input, itr4_result)

        assert data["formType"] == "ITR-4"
        for key in ("personalInfo", "businessIncome", "otherIncome",
                     "deductions", "taxComputation", "taxPayments", "verification"):
            assert key in data, f"Missing key: {key}"

    def test_business_income(self, itr4_input, itr4_result):
        """businessIncome has turnover, rate, and deemed profit."""
        data = generate_itr4_json(itr4_input, itr4_result)
        biz = data["businessIncome"]

        assert biz["grossTurnover"] == 5000000.0
        assert biz["presumptiveRate"] == 8.0
        assert biz["deemedProfit"] == 400000.0  # 5M * 8%

    def test_deductions(self, itr4_input, itr4_result):
        """deductions section has correct values."""
        data = generate_itr4_json(itr4_input, itr4_result)
        ded = data["deductions"]

        assert ded["section80C"] == 100000.0
        assert ded["totalDeductions"] >= 0

    def test_both_regimes(self, itr4_input, itr4_result):
        """taxComputation contains both old and new regime breakdowns."""
        data = generate_itr4_json(itr4_input, itr4_result)
        tc = data["taxComputation"]

        assert tc["oldRegime"]["taxableIncome"] >= 0
        assert tc["newRegime"]["taxableIncome"] >= 0

    def test_tax_payments(self, itr4_input, itr4_result):
        """taxPayments includes TDS and advance tax."""
        data = generate_itr4_json(itr4_input, itr4_result)
        tp = data["taxPayments"]

        assert tp["tdsTotal"] == 30000.0
        assert tp["totalPaid"] == 30000.0


# ============================================================
# itr_json.py — itr_json_to_string
# ============================================================

class TestItrJsonToString:
    """Tests for JSON serialization."""

    def test_valid_json_output(self, itr1_input, itr1_result):
        """itr_json_to_string produces valid JSON string."""
        import json

        data = generate_itr1_json(itr1_input, itr1_result)
        json_str = itr_json_to_string(data)

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["formType"] == "ITR-1"

    def test_pretty_printed(self, itr1_input, itr1_result):
        """Output is indented (pretty-printed)."""
        data = generate_itr1_json(itr1_input, itr1_result)
        json_str = itr_json_to_string(data)

        # Pretty printed JSON has newlines and indentation
        assert "\n" in json_str
        assert "  " in json_str

    def test_zero_input_produces_valid_json(self):
        """Zero-input ITR-1 still produces valid JSON."""
        import json

        inp = ITR1Input()
        result = compute_itr1(inp)
        data = generate_itr1_json(inp, result)
        json_str = itr_json_to_string(data)

        parsed = json.loads(json_str)
        assert parsed["formType"] == "ITR-1"
        assert parsed["incomeDetails"]["grossSalary"] == 0.0


# ============================================================
# itr_pdf.py — generate_itr1_pdf
# ============================================================

class TestGenerateItr1Pdf:
    """Tests for ITR-1 PDF generation."""

    def test_returns_bytes(self, itr1_input, itr1_result):
        """generate_itr1_pdf returns bytes."""
        pdf_bytes = generate_itr1_pdf(itr1_input, itr1_result)
        assert isinstance(pdf_bytes, bytes)

    def test_pdf_header(self, itr1_input, itr1_result):
        """Output starts with PDF header magic bytes."""
        pdf_bytes = generate_itr1_pdf(itr1_input, itr1_result)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_pdf_non_empty(self, itr1_input, itr1_result):
        """Generated PDF has reasonable size (> 1KB)."""
        pdf_bytes = generate_itr1_pdf(itr1_input, itr1_result)
        assert len(pdf_bytes) > 1024

    def test_pdf_with_zero_input(self):
        """Zero-input ITR-1 still generates valid PDF."""
        inp = ITR1Input()
        result = compute_itr1(inp)
        pdf_bytes = generate_itr1_pdf(inp, result)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_pdf_with_high_income(self):
        """High-income ITR-1 generates valid PDF (no errors)."""
        inp = ITR1Input(
            salary_income=Decimal("10000000"),  # 1 crore
            section_80c=Decimal("150000"),
            tds_total=Decimal("2500000"),
        )
        result = compute_itr1(inp)
        pdf_bytes = generate_itr1_pdf(inp, result)
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 1024


# ============================================================
# itr_pdf.py — generate_itr4_pdf
# ============================================================

class TestGenerateItr4Pdf:
    """Tests for ITR-4 PDF generation."""

    def test_returns_bytes(self, itr4_input, itr4_result):
        """generate_itr4_pdf returns bytes."""
        pdf_bytes = generate_itr4_pdf(itr4_input, itr4_result)
        assert isinstance(pdf_bytes, bytes)

    def test_pdf_header(self, itr4_input, itr4_result):
        """Output starts with PDF header magic bytes."""
        pdf_bytes = generate_itr4_pdf(itr4_input, itr4_result)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_pdf_non_empty(self, itr4_input, itr4_result):
        """Generated PDF has reasonable size (> 1KB)."""
        pdf_bytes = generate_itr4_pdf(itr4_input, itr4_result)
        assert len(pdf_bytes) > 1024

    def test_pdf_with_professional_income(self):
        """ITR-4 for professional (44ADA) generates valid PDF."""
        inp = ITR4Input(
            gross_receipts=Decimal("3000000"),
            professional_rate=Decimal("50"),
            gross_turnover=Decimal("0"),
            section_80c=Decimal("100000"),
        )
        result = compute_itr4(inp)
        pdf_bytes = generate_itr4_pdf(inp, result)
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 1024

    def test_pdf_with_zero_input(self):
        """Zero-input ITR-4 still generates valid PDF."""
        inp = ITR4Input()
        result = compute_itr4(inp)
        pdf_bytes = generate_itr4_pdf(inp, result)
        assert pdf_bytes[:5] == b"%PDF-"


# ============================================================
# Integration: ITR computation → JSON → PDF pipeline
# ============================================================

class TestItrPipeline:
    """End-to-end tests for the compute → generate pipeline."""

    def test_itr1_full_pipeline(self):
        """ITR-1: compute → JSON → PDF all succeed."""
        inp = ITR1Input(
            pan="ABCDE1234F",
            name="Pipeline Test",
            salary_income=Decimal("800000"),
            section_80c=Decimal("100000"),
            tds_total=Decimal("50000"),
        )
        result = compute_itr1(inp)

        # JSON generation
        json_data = generate_itr1_json(inp, result)
        assert json_data["formType"] == "ITR-1"
        assert json_data["personalInfo"]["pan"] == "ABCDE1234F"

        # JSON serialization
        json_str = itr_json_to_string(json_data)
        assert len(json_str) > 100

        # PDF generation
        pdf_bytes = generate_itr1_pdf(inp, result)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_itr4_full_pipeline(self):
        """ITR-4: compute → JSON → PDF all succeed."""
        inp = ITR4Input(
            pan="XYZAB5678C",
            name="Business Pipeline",
            gross_turnover=Decimal("2000000"),
            presumptive_rate=Decimal("8"),
            tds_total=Decimal("10000"),
        )
        result = compute_itr4(inp)

        # JSON generation
        json_data = generate_itr4_json(inp, result)
        assert json_data["formType"] == "ITR-4"
        assert json_data["businessIncome"]["deemedProfit"] == 160000.0

        # PDF generation
        pdf_bytes = generate_itr4_pdf(inp, result)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_itr1_recommended_regime_matches(self):
        """The recommended regime in JSON matches the computed result."""
        inp = ITR1Input(
            salary_income=Decimal("1500000"),
            section_80c=Decimal("150000"),
            section_80d=Decimal("50000"),
        )
        result = compute_itr1(inp)
        json_data = generate_itr1_json(inp, result)

        assert json_data["taxComputation"]["recommendedRegime"] == result.recommended_regime
        assert json_data["taxComputation"]["savings"] == float(result.savings)

    def test_itr1_tax_consistency(self):
        """JSON tax values match the computed result."""
        inp = ITR1Input(
            salary_income=Decimal("1200000"),
            tds_total=Decimal("100000"),
        )
        result = compute_itr1(inp)
        json_data = generate_itr1_json(inp, result)

        old_json = json_data["taxComputation"]["oldRegime"]
        new_json = json_data["taxComputation"]["newRegime"]

        assert old_json["totalTaxLiability"] == float(result.old_regime.total_tax_liability)
        assert new_json["totalTaxLiability"] == float(result.new_regime.total_tax_liability)
