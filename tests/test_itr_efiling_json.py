"""Tests for the e-filing JSON generators (ITR-1 and ITR-4)."""

from decimal import Decimal

import pytest

from app.domain.services.itr_service import (
    ITR1Input,
    ITR4Input,
    compute_itr1,
    compute_itr4,
)
from app.domain.services.itr_json import (
    generate_itr1_json,
    generate_itr4_json,
    generate_itr1_efiling_json,
    generate_itr4_efiling_json,
    itr_json_to_string,
    _breakdown_to_dict,
    _fl,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def itr1_input():
    return ITR1Input(
        pan="ABCDE1234F",
        name="Test User",
        assessment_year="2025-26",
        salary_income=Decimal("1200000"),
        standard_deduction=Decimal("75000"),
        house_property_income=Decimal("0"),
        other_income=Decimal("50000"),
        section_80c=Decimal("150000"),
        section_80d=Decimal("25000"),
        section_80tta=Decimal("10000"),
        tds_total=Decimal("80000"),
        advance_tax=Decimal("0"),
        self_assessment_tax=Decimal("0"),
    )


@pytest.fixture
def itr1_result(itr1_input):
    return compute_itr1(itr1_input)


@pytest.fixture
def itr4_input():
    return ITR4Input(
        pan="FGHIJ5678K",
        name="Business User",
        assessment_year="2025-26",
        gross_turnover=Decimal("5000000"),
        presumptive_rate=Decimal("8"),
        gross_receipts=Decimal("0"),
        professional_rate=Decimal("50"),
        salary_income=Decimal("0"),
        house_property_income=Decimal("0"),
        other_income=Decimal("0"),
        section_80c=Decimal("150000"),
        section_80d=Decimal("25000"),
        other_deductions=Decimal("0"),
        tds_total=Decimal("20000"),
        advance_tax=Decimal("10000"),
    )


@pytest.fixture
def itr4_result(itr4_input):
    return compute_itr4(itr4_input)


# ---------------------------------------------------------------------------
# _fl helper
# ---------------------------------------------------------------------------

class TestFlHelper:

    def test_decimal(self):
        assert _fl(Decimal("123.456")) == 123.46

    def test_float(self):
        assert _fl(99.999) == 100.0

    def test_zero(self):
        assert _fl(Decimal("0")) == 0.0

    def test_negative(self):
        assert _fl(Decimal("-500.123")) == -500.12


# ---------------------------------------------------------------------------
# generate_itr1_json tests
# ---------------------------------------------------------------------------

class TestGenerateITR1Json:

    def test_form_type(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        assert data["formType"] == "ITR-1"

    def test_assessment_year(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        assert data["assessmentYear"] == "2025-26"

    def test_personal_info(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        assert data["personalInfo"]["pan"] == "ABCDE1234F"
        assert data["personalInfo"]["name"] == "Test User"

    def test_income_details(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        inc = data["incomeDetails"]
        assert inc["grossSalary"] == 1200000.0
        assert inc["standardDeduction"] == 75000.0
        assert inc["netSalary"] == 1125000.0
        assert inc["otherIncome"] == 50000.0

    def test_deductions_section(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        ded = data["deductions"]
        assert ded["section80C"] == 150000.0
        assert ded["section80D"] == 25000.0
        assert ded["section80TTA"] == 10000.0

    def test_tax_computation_section(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        tc = data["taxComputation"]
        assert tc["recommendedRegime"] in ("old", "new")
        assert isinstance(tc["savings"], float)
        assert "oldRegime" in tc
        assert "newRegime" in tc

    def test_tax_payments(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        tp = data["taxPayments"]
        assert tp["tdsTotal"] == 80000.0
        assert tp["totalPaid"] == 80000.0

    def test_verification_present(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        assert "verification" in data
        assert "generatedAt" in data["verification"]
        assert "GST-ITR Bot" in data["verification"]["computedBy"]

    def test_zero_salary(self):
        inp = ITR1Input(salary_income=Decimal("0"), other_income=Decimal("100000"))
        result = compute_itr1(inp)
        data = generate_itr1_json(inp, result)
        assert data["incomeDetails"]["grossSalary"] == 0.0
        assert data["incomeDetails"]["netSalary"] == 0.0


# ---------------------------------------------------------------------------
# generate_itr4_json tests
# ---------------------------------------------------------------------------

class TestGenerateITR4Json:

    def test_form_type(self, itr4_input, itr4_result):
        data = generate_itr4_json(itr4_input, itr4_result)
        assert data["formType"] == "ITR-4"

    def test_business_income(self, itr4_input, itr4_result):
        data = generate_itr4_json(itr4_input, itr4_result)
        biz = data["businessIncome"]
        assert biz["grossTurnover"] == 5000000.0
        assert biz["presumptiveRate"] == 8.0
        assert biz["deemedProfit"] == 400000.0

    def test_deductions(self, itr4_input, itr4_result):
        data = generate_itr4_json(itr4_input, itr4_result)
        ded = data["deductions"]
        assert ded["section80C"] == 150000.0
        assert ded["section80D"] == 25000.0

    def test_tax_payments(self, itr4_input, itr4_result):
        data = generate_itr4_json(itr4_input, itr4_result)
        tp = data["taxPayments"]
        assert tp["tdsTotal"] == 20000.0
        assert tp["advanceTax"] == 10000.0
        assert tp["totalPaid"] == 30000.0

    def test_zero_turnover(self):
        inp = ITR4Input(gross_turnover=Decimal("0"))
        result = compute_itr4(inp)
        data = generate_itr4_json(inp, result)
        assert data["businessIncome"]["deemedProfit"] == 0.0


# ---------------------------------------------------------------------------
# generate_itr1_efiling_json tests (portal schema)
# ---------------------------------------------------------------------------

class TestITR1EfilingJson:

    def test_form_metadata(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        assert data["Form_ITR1"]["FormName"] == "ITR-1"
        assert data["Form_ITR1"]["AssessmentYear"] == "202526"

    def test_personal_info_structure(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        pi = data["PersonalInfo"]
        assert pi["PAN"] == "ABCDE1234F"
        assert "AssesseeName" in pi
        assert "FirstName" in pi["AssesseeName"]

    def test_personal_info_with_extra(self, itr1_input, itr1_result):
        personal = {
            "firstName": "Test",
            "surName": "User",
            "dob": "1990-01-15",
            "aadhaar": "123456789012",
        }
        data = generate_itr1_efiling_json(itr1_input, itr1_result, personal_info=personal)
        assert data["PersonalInfo"]["AssesseeName"]["FirstName"] == "Test"
        assert data["PersonalInfo"]["AssesseeName"]["SurNameOrOrgName"] == "User"
        assert data["PersonalInfo"]["AadhaarCardNo"] == "123456789012"

    def test_filing_status(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        assert data["FilingStatus"]["ReturnFileSec"] == 11
        assert data["FilingStatus"]["OptOutNewTaxRegime"] in ("Y", "N")

    def test_income_deductions_section(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        inc = data["ITR1_IncomeDeductions"]
        assert inc["GrossSalary"] == 1200000.0
        assert isinstance(inc["GrossTotIncome"], float)
        assert "DeductUndChapVIA" in inc
        via = inc["DeductUndChapVIA"]
        assert via["Section80C"] == 150000.0
        assert via["Section80D"] == 25000.0
        assert via["Section80TTA"] == 10000.0

    def test_tax_computation_section(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        tc = data["ITR1_TaxComputation"]
        assert isinstance(tc["TotalTaxPayable"], float)
        assert isinstance(tc["Rebate87A"], float)
        assert isinstance(tc["EducationCess"], float)
        assert isinstance(tc["GrossTaxLiability"], float)
        paid = tc["TotalTaxesPaid"]
        assert paid["TDS"] == 80000.0
        assert paid["TCS"] == 0.0

    def test_tds_on_salaries_key(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        assert "TDSonSalaries" in data
        assert isinstance(data["TDSonSalaries"], list)

    def test_verification_section(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        v = data["Verification"]
        assert "Declaration" in v
        assert "GeneratedAt" in v
        assert "incometax.gov.in" in v["Disclaimer"]

    def test_all_values_are_numeric(self, itr1_input, itr1_result):
        data = generate_itr1_efiling_json(itr1_input, itr1_result)
        inc = data["ITR1_IncomeDeductions"]
        for key in ["GrossSalary", "Salary", "IncomeFromHP", "IncomeOthSrc", "GrossTotIncome", "TotalIncome"]:
            assert isinstance(inc[key], float), f"{key} is not float"


# ---------------------------------------------------------------------------
# generate_itr4_efiling_json tests (portal schema)
# ---------------------------------------------------------------------------

class TestITR4EfilingJson:

    def test_form_metadata(self, itr4_input, itr4_result):
        data = generate_itr4_efiling_json(itr4_input, itr4_result)
        assert data["Form_ITR4"]["FormName"] == "ITR-4"
        assert data["Form_ITR4"]["AssessmentYear"] == "202526"

    def test_schedule_bp(self, itr4_input, itr4_result):
        data = generate_itr4_efiling_json(itr4_input, itr4_result)
        bp = data["ScheduleBP"]
        assert bp["NatOfBus44AD"]["GrossReceipts"] == 5000000.0
        assert bp["NatOfBus44AD"]["DeemedProfit"] == 400000.0
        assert isinstance(bp["ProfitFromBP"], float)

    def test_income_deductions(self, itr4_input, itr4_result):
        data = generate_itr4_efiling_json(itr4_input, itr4_result)
        inc = data["ITR4_IncomeDeductions"]
        assert isinstance(inc["GrossTotIncome"], float)
        assert isinstance(inc["TotalIncome"], float)
        via = inc["DeductUndChapVIA"]
        assert via["Section80C"] == 150000.0

    def test_tax_computation(self, itr4_input, itr4_result):
        data = generate_itr4_efiling_json(itr4_input, itr4_result)
        tc = data["ITR4_TaxComputation"]
        assert isinstance(tc["GrossTaxLiability"], float)
        paid = tc["TotalTaxesPaid"]
        assert paid["TDS"] == 20000.0
        assert paid["AdvanceTax"] == 10000.0
        assert paid["TotalPaid"] == 30000.0
        assert paid["TCS"] == 0.0

    def test_verification_section(self, itr4_input, itr4_result):
        data = generate_itr4_efiling_json(itr4_input, itr4_result)
        assert "incometax.gov.in" in data["Verification"]["Disclaimer"]

    def test_professional_income(self):
        inp = ITR4Input(
            gross_turnover=Decimal("0"),
            gross_receipts=Decimal("2000000"),
            professional_rate=Decimal("50"),
        )
        result = compute_itr4(inp)
        data = generate_itr4_efiling_json(inp, result)
        bp = data["ScheduleBP"]
        assert bp["NatOfBus44ADA"]["ProfessionalIncome"] == 1000000.0

    def test_zero_turnover_efiling(self):
        inp = ITR4Input(gross_turnover=Decimal("0"))
        result = compute_itr4(inp)
        data = generate_itr4_efiling_json(inp, result)
        assert data["ScheduleBP"]["NatOfBus44AD"]["DeemedProfit"] == 0.0


# ---------------------------------------------------------------------------
# itr_json_to_string tests
# ---------------------------------------------------------------------------

class TestITRJsonToString:

    def test_produces_valid_json_string(self, itr1_input, itr1_result):
        import json
        data = generate_itr1_json(itr1_input, itr1_result)
        s = itr_json_to_string(data)
        parsed = json.loads(s)
        assert parsed["formType"] == "ITR-1"

    def test_pretty_printed(self, itr1_input, itr1_result):
        data = generate_itr1_json(itr1_input, itr1_result)
        s = itr_json_to_string(data)
        # Pretty-printed JSON should have newlines
        assert "\n" in s


# ---------------------------------------------------------------------------
# _breakdown_to_dict tests
# ---------------------------------------------------------------------------

class TestBreakdownToDict:

    def test_keys_are_camel_case(self, itr1_result):
        bd = _breakdown_to_dict(itr1_result.old_regime)
        assert "grossTotalIncome" in bd
        assert "totalDeductions" in bd
        assert "taxableIncome" in bd
        assert "taxOnIncome" in bd
        assert "rebate87A" in bd
        assert "surcharge" in bd
        assert "healthCess" in bd
        assert "totalTaxLiability" in bd
        assert "taxesPaid" in bd
        assert "taxPayable" in bd
        assert "slabDetails" in bd

    def test_values_are_floats(self, itr1_result):
        bd = _breakdown_to_dict(itr1_result.old_regime)
        for key in ["grossTotalIncome", "totalDeductions", "taxableIncome",
                    "taxOnIncome", "rebate87A", "surcharge", "healthCess",
                    "totalTaxLiability", "taxesPaid", "taxPayable"]:
            assert isinstance(bd[key], float), f"{key} should be float"

    def test_regime_field(self, itr1_result):
        bd = _breakdown_to_dict(itr1_result.old_regime)
        assert bd["regime"] == "old"
        bd_new = _breakdown_to_dict(itr1_result.new_regime)
        assert bd_new["regime"] == "new"
