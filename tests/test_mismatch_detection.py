"""Tests for the AIS / 26AS / Form 16 / GST mismatch detection engine."""

from decimal import Decimal

import pytest

from app.domain.services.itr_form_parser import (
    ParsedAIS,
    ParsedForm16,
    ParsedForm26AS,
)
from app.domain.services.mismatch_detection import (
    Mismatch,
    MismatchReport,
    _compare_tds,
    _compare_salary,
    _compare_income_sources,
    _compare_sft,
    _compare_gst_turnover,
    detect_mismatches,
    format_mismatch_report,
    mismatch_to_dict,
    report_to_dict,
    dict_to_report,
)


@pytest.fixture
def form16_basic():
    return ParsedForm16(
        employer_name="ABC Corp",
        employee_pan="ABCDE1234F",
        gross_salary=Decimal("1200000"),
        total_tax_deducted=Decimal("80000"),
    )


@pytest.fixture
def form26as_matching():
    return ParsedForm26AS(pan="ABCDE1234F", total_tds=Decimal("80000"))


@pytest.fixture
def ais_matching():
    return ParsedAIS(pan="ABCDE1234F", salary_income=Decimal("1200000"))


class TestCompareTDS:

    def test_identical_tds_no_mismatch(self, form16_basic, form26as_matching):
        assert _compare_tds(form16_basic, form26as_matching) == []

    def test_both_zero_no_mismatch(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("0"))
        f26 = ParsedForm26AS(total_tds=Decimal("0"))
        assert _compare_tds(f16, f26) == []

    def test_both_none_treated_as_zero(self):
        f16 = ParsedForm16(total_tax_deducted=None)
        f26 = ParsedForm26AS(total_tds=None)
        assert _compare_tds(f16, f26) == []

    def test_small_diff_below_warning(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("80400"))
        assert _compare_tds(f16, f26) == []

    def test_diff_exactly_at_warning(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("80500"))
        assert _compare_tds(f16, f26) == []

    def test_diff_just_above_warning(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("80501"))
        result = _compare_tds(f16, f26)
        assert len(result) == 1
        assert result[0].severity == "warning"
        assert result[0].category == "tds"
        assert result[0].difference == Decimal("501")

    def test_diff_at_critical_boundary(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("85000"))
        result = _compare_tds(f16, f26)
        assert len(result) == 1
        assert result[0].severity == "warning"

    def test_diff_above_critical(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("90000"))
        result = _compare_tds(f16, f26)
        assert len(result) == 1
        assert result[0].severity == "critical"
        assert result[0].difference == Decimal("10000")
        assert result[0].field == "tds_total"
        assert result[0].source_a == "form16"
        assert result[0].source_b == "26as"

    def test_direction_does_not_matter(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("90000"))
        f26 = ParsedForm26AS(total_tds=Decimal("80000"))
        result = _compare_tds(f16, f26)
        assert len(result) == 1
        assert result[0].severity == "critical"


class TestCompareSalary:

    def test_identical_salary(self, form16_basic, ais_matching):
        assert _compare_salary(form16_basic, ais_matching) == []

    def test_both_zero(self):
        f16 = ParsedForm16(gross_salary=Decimal("0"))
        ais = ParsedAIS(salary_income=Decimal("0"))
        assert _compare_salary(f16, ais) == []

    def test_both_none(self):
        f16 = ParsedForm16(gross_salary=None)
        ais = ParsedAIS(salary_income=None)
        assert _compare_salary(f16, ais) == []

    def test_small_pct_diff(self):
        f16 = ParsedForm16(gross_salary=Decimal("1000000"))
        ais = ParsedAIS(salary_income=Decimal("1040000"))
        assert _compare_salary(f16, ais) == []

    def test_above_5_percent(self):
        f16 = ParsedForm16(gross_salary=Decimal("1000000"))
        ais = ParsedAIS(salary_income=Decimal("1100000"))
        result = _compare_salary(f16, ais)
        assert len(result) == 1
        assert result[0].severity == "warning"
        assert result[0].category == "income"

    def test_one_zero_one_nonzero(self):
        f16 = ParsedForm16(gross_salary=Decimal("1000000"))
        ais = ParsedAIS(salary_income=Decimal("0"))
        assert len(_compare_salary(f16, ais)) == 1


class TestCompareIncomeSources:

    def test_no_extra_income(self):
        assert _compare_income_sources(ParsedForm16(), ParsedAIS()) == []

    def test_interest_income(self):
        result = _compare_income_sources(ParsedForm16(), ParsedAIS(interest_income=Decimal("50000")))
        interest = [m for m in result if m.field == "interest_income"]
        assert len(interest) == 1 and interest[0].severity == "critical"

    def test_dividend_income(self):
        result = _compare_income_sources(ParsedForm16(), ParsedAIS(dividend_income=Decimal("25000")))
        assert any(m.field == "dividend_income" and m.severity == "critical" for m in result)

    def test_rental_income(self):
        result = _compare_income_sources(ParsedForm16(), ParsedAIS(rental_income=Decimal("180000")))
        assert any(m.field == "rental_income" and m.severity == "critical" for m in result)

    def test_multiple_income_sources(self):
        ais = ParsedAIS(interest_income=Decimal("30000"), dividend_income=Decimal("15000"), rental_income=Decimal("120000"))
        result = _compare_income_sources(ParsedForm16(), ais)
        assert len(result) == 3

    def test_zero_income_not_flagged(self):
        ais = ParsedAIS(interest_income=Decimal("0"), dividend_income=Decimal("0"), rental_income=Decimal("0"))
        assert _compare_income_sources(ParsedForm16(), ais) == []


class TestCompareSFT:

    def test_empty(self):
        assert _compare_sft(ParsedAIS(sft_transactions=[])) == []

    def test_none(self):
        assert _compare_sft(ParsedAIS(sft_transactions=None)) == []

    def test_below_threshold(self):
        assert _compare_sft(ParsedAIS(sft_transactions=[{"amount": 500000}])) == []

    def test_at_threshold(self):
        result = _compare_sft(ParsedAIS(sft_transactions=[{"amount": 1000000, "description": "Sale"}]))
        assert len(result) == 1 and result[0].severity == "critical"

    def test_above_threshold(self):
        result = _compare_sft(ParsedAIS(sft_transactions=[{"amount": 5000000}]))
        assert result[0].difference == Decimal("5000000")

    def test_mixed(self):
        txns = [{"amount": 500000}, {"amount": 2000000}, {"amount": 800000}, {"amount": 1500000}]
        assert len(_compare_sft(ParsedAIS(sft_transactions=txns))) == 2

    def test_type_fallback(self):
        result = _compare_sft(ParsedAIS(sft_transactions=[{"amount": 1500000, "type": "Cash deposit"}]))
        assert "Cash deposit" in result[0].suggested_action


class TestCompareGSTTurnover:

    def test_both_zero(self):
        assert _compare_gst_turnover(ParsedAIS(business_turnover=Decimal("0")), Decimal("0")) == []

    def test_matching(self):
        assert _compare_gst_turnover(ParsedAIS(business_turnover=Decimal("5000000")), Decimal("5000000")) == []

    def test_within_threshold(self):
        assert _compare_gst_turnover(ParsedAIS(business_turnover=Decimal("5000000")), Decimal("4600000")) == []

    def test_above_threshold(self):
        result = _compare_gst_turnover(ParsedAIS(business_turnover=Decimal("5000000")), Decimal("4000000"))
        assert len(result) == 1 and result[0].severity == "critical"

    def test_one_zero(self):
        result = _compare_gst_turnover(ParsedAIS(business_turnover=Decimal("5000000")), Decimal("0"))
        assert len(result) == 1 and result[0].severity == "critical"


class TestDetectMismatches:

    def test_no_documents(self):
        report = detect_mismatches()
        assert report.mismatches == [] and report.documents_compared == []

    def test_only_form16(self):
        report = detect_mismatches(form16=ParsedForm16(gross_salary=Decimal("1200000")))
        assert report.documents_compared == ["form16"] and report.mismatches == []

    def test_matching_form16_26as(self, form16_basic, form26as_matching):
        report = detect_mismatches(form16=form16_basic, form26as=form26as_matching)
        assert report.total_critical == 0

    def test_critical_tds(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("60000"))
        assert detect_mismatches(form16=f16, form26as=f26).total_critical == 1

    def test_full_comparison(self):
        f16 = ParsedForm16(gross_salary=Decimal("1200000"), total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("80200"))
        ais = ParsedAIS(
            salary_income=Decimal("1200000"), interest_income=Decimal("35000"),
            dividend_income=Decimal("10000"),
            sft_transactions=[{"amount": 2000000, "description": "Property"}],
        )
        report = detect_mismatches(form16=f16, form26as=f26, ais=ais)
        assert report.total_critical >= 3

    def test_gst_flag_set(self):
        ais = ParsedAIS(business_turnover=Decimal("5000000"))
        assert detect_mismatches(ais=ais, gst_turnover=Decimal("3000000")).has_gst_comparison is True

    def test_gst_flag_not_set_zero(self):
        assert detect_mismatches(ais=ParsedAIS(), gst_turnover=Decimal("0")).has_gst_comparison is False

    def test_gst_flag_not_set_none(self):
        assert detect_mismatches(ais=ParsedAIS(), gst_turnover=None).has_gst_comparison is False

    def test_counts_accurate(self):
        f16 = ParsedForm16(total_tax_deducted=Decimal("80000"))
        f26 = ParsedForm26AS(total_tds=Decimal("81000"))
        ais = ParsedAIS(interest_income=Decimal("50000"))
        report = detect_mismatches(form16=f16, form26as=f26, ais=ais)
        assert report.total_warnings == 1 and report.total_critical == 1


class TestFormatMismatchReport:

    def test_no_mismatches(self):
        assert "No mismatches found" in format_mismatch_report(MismatchReport())

    def test_with_mismatches(self):
        m = Mismatch(
            field="tds_total", source_a="form16", source_b="26as",
            value_a=Decimal("80000"), value_b=Decimal("90000"),
            difference=Decimal("10000"), severity="critical",
            suggested_action="Check TDS", category="tds",
        )
        text = format_mismatch_report(MismatchReport(mismatches=[m], total_critical=1, total_warnings=0))
        assert "1 mismatch(es)" in text and "[!!]" in text

    def test_critical_sorted_first(self):
        w = Mismatch(field="salary", source_a="f16", source_b="ais", value_a=Decimal("1000000"),
                     value_b=Decimal("1100000"), difference=Decimal("100000"), severity="warning",
                     suggested_action="Check", category="income")
        c = Mismatch(field="interest", source_a="f16", source_b="ais", value_a=Decimal("0"),
                     value_b=Decimal("50000"), difference=Decimal("50000"), severity="critical",
                     suggested_action="Declare", category="income")
        text = format_mismatch_report(MismatchReport(mismatches=[w, c], total_warnings=1, total_critical=1))
        assert text.find("[!!]") < text.find("[!]")


class TestMismatchSerialization:

    def test_mismatch_to_dict(self):
        m = Mismatch(field="tds_total", source_a="form16", source_b="26as",
                     value_a=Decimal("80000"), value_b=Decimal("90000"),
                     difference=Decimal("10000"), severity="critical",
                     suggested_action="Verify", category="tds")
        d = mismatch_to_dict(m)
        assert d["field"] == "tds_total" and d["value_a"] == "80000"

    def test_report_roundtrip(self):
        m = Mismatch(field="salary_income", source_a="form16", source_b="ais",
                     value_a=Decimal("1200000"), value_b=Decimal("1300000"),
                     difference=Decimal("100000"), severity="warning",
                     suggested_action="Check", category="income")
        report = MismatchReport(mismatches=[m], total_warnings=1, total_critical=0,
                                documents_compared=["form16", "ais"])
        restored = dict_to_report(report_to_dict(report))
        assert restored.mismatches[0].value_a == Decimal("1200000")
        assert restored.total_warnings == 1

    def test_dict_to_report_empty(self):
        assert dict_to_report({}).mismatches == []

    def test_dict_to_report_none(self):
        assert dict_to_report(None).mismatches == []
