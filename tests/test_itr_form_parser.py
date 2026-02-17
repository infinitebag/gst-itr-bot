"""Tests for ITR form document parser — merge logic, formatters, and converters."""

from decimal import Decimal

import pytest

from app.domain.services.itr_form_parser import (
    ParsedForm16,
    ParsedForm26AS,
    ParsedAIS,
    MergedITRData,
    merge_form16,
    merge_form26as,
    merge_ais,
    format_review_summary,
    merged_to_itr1_input,
    merged_to_itr4_input,
    merged_to_dict,
    dict_to_merged,
    dict_to_parsed_form16,
    dict_to_parsed_form26as,
    dict_to_parsed_ais,
    ITR_DOC_EDITABLE_FIELDS,
)


class TestParsedForm16:
    """Verify ParsedForm16 dataclass defaults."""

    def test_defaults_are_none(self):
        f16 = ParsedForm16()
        assert f16.employer_name is None
        assert f16.gross_salary is None
        assert f16.total_tax_deducted is None
        assert f16.section_80c is None

    def test_with_values(self):
        f16 = ParsedForm16(
            employer_name="Infosys Ltd",
            gross_salary=Decimal("1200000"),
            section_80c=Decimal("150000"),
            total_tax_deducted=Decimal("80000"),
        )
        assert f16.employer_name == "Infosys Ltd"
        assert f16.gross_salary == Decimal("1200000")


class TestMergeForm16:
    """Verify Form 16 merge into MergedITRData."""

    def test_merge_into_empty(self):
        merged = MergedITRData()
        f16 = ParsedForm16(
            employee_pan="ABCDE1234F",
            assessment_year="2025-26",
            gross_salary=Decimal("1200000"),
            section_80c=Decimal("150000"),
            section_80d=Decimal("25000"),
            total_tax_deducted=Decimal("80000"),
        )
        result = merge_form16(merged, f16)
        assert result.pan == "ABCDE1234F"
        assert result.salary_income == Decimal("1200000")
        assert result.section_80c == Decimal("150000")
        assert result.section_80d == Decimal("25000")
        assert result.tds_total == Decimal("80000")
        assert "form16" in result.sources

    def test_merge_takes_maximum_salary(self):
        """When existing salary is higher, keep existing."""
        merged = MergedITRData(salary_income=Decimal("1500000"))
        f16 = ParsedForm16(gross_salary=Decimal("1200000"))
        result = merge_form16(merged, f16)
        assert result.salary_income == Decimal("1500000")

    def test_merge_upgrades_salary(self):
        """When Form 16 salary is higher, use Form 16."""
        merged = MergedITRData(salary_income=Decimal("800000"))
        f16 = ParsedForm16(gross_salary=Decimal("1200000"))
        result = merge_form16(merged, f16)
        assert result.salary_income == Decimal("1200000")

    def test_none_fields_not_overwritten(self):
        """None fields in Form 16 should not reset existing data."""
        merged = MergedITRData(section_80c=Decimal("100000"), tds_total=Decimal("50000"))
        f16 = ParsedForm16()  # all None
        result = merge_form16(merged, f16)
        assert result.section_80c == Decimal("100000")
        assert result.tds_total == Decimal("50000")

    def test_house_property_income(self):
        merged = MergedITRData()
        f16 = ParsedForm16(house_property_income=Decimal("-200000"))
        result = merge_form16(merged, f16)
        assert result.house_property_income == Decimal("-200000")

    def test_no_duplicate_source(self):
        merged = MergedITRData(sources=["form16"])
        f16 = ParsedForm16(gross_salary=Decimal("1000000"))
        result = merge_form16(merged, f16)
        assert result.sources.count("form16") == 1


class TestMergeForm26AS:
    """Verify Form 26AS merge."""

    def test_merge_tds_overrides(self):
        """26AS TDS is authoritative — should override existing."""
        merged = MergedITRData(tds_total=Decimal("50000"))
        f26 = ParsedForm26AS(total_tds=Decimal("95000"))
        result = merge_form26as(merged, f26)
        assert result.tds_total == Decimal("95000")

    def test_merge_advance_tax(self):
        merged = MergedITRData()
        f26 = ParsedForm26AS(
            advance_tax_paid=Decimal("30000"),
            self_assessment_tax=Decimal("10000"),
        )
        result = merge_form26as(merged, f26)
        assert result.advance_tax == Decimal("30000")
        assert result.self_assessment_tax == Decimal("10000")

    def test_merge_pan(self):
        merged = MergedITRData()
        f26 = ParsedForm26AS(pan="XYZAB1234G")
        result = merge_form26as(merged, f26)
        assert result.pan == "XYZAB1234G"
        assert "26as" in result.sources

    def test_none_tds_keeps_existing(self):
        merged = MergedITRData(tds_total=Decimal("75000"))
        f26 = ParsedForm26AS()
        result = merge_form26as(merged, f26)
        assert result.tds_total == Decimal("75000")


class TestMergeAIS:
    """Verify AIS merge."""

    def test_merge_income_fields(self):
        merged = MergedITRData()
        ais = ParsedAIS(
            salary_income=Decimal("1000000"),
            interest_income=Decimal("50000"),
            dividend_income=Decimal("20000"),
            rental_income=Decimal("120000"),
        )
        result = merge_ais(merged, ais)
        assert result.salary_income == Decimal("1000000")
        assert result.interest_income == Decimal("50000")
        assert result.dividend_income == Decimal("20000")
        assert result.house_property_income == Decimal("120000")
        assert result.other_income == Decimal("70000")  # interest + dividend
        assert "ais" in result.sources

    def test_ais_tds_ignored_when_26as_present(self):
        """If 26AS already merged, AIS TDS should be ignored."""
        merged = MergedITRData(tds_total=Decimal("95000"), sources=["26as"])
        ais = ParsedAIS(tds_total=Decimal("80000"))
        result = merge_ais(merged, ais)
        assert result.tds_total == Decimal("95000")  # 26AS value kept

    def test_ais_tds_used_without_26as(self):
        """Without 26AS, AIS TDS should be used."""
        merged = MergedITRData(tds_total=Decimal("50000"))
        ais = ParsedAIS(tds_total=Decimal("80000"))
        result = merge_ais(merged, ais)
        assert result.tds_total == Decimal("80000")

    def test_business_turnover(self):
        merged = MergedITRData()
        ais = ParsedAIS(business_turnover=Decimal("5000000"))
        result = merge_ais(merged, ais)
        assert result.business_turnover == Decimal("5000000")


class TestMultiDocumentMerge:
    """Verify sequential merge of Form 16 + 26AS + AIS."""

    def test_full_merge(self):
        merged = MergedITRData()

        # Step 1: Form 16
        f16 = ParsedForm16(
            employee_pan="ABCDE1234F",
            gross_salary=Decimal("1200000"),
            section_80c=Decimal("150000"),
            section_80d=Decimal("25000"),
            section_80ccd_1b=Decimal("50000"),
            total_tax_deducted=Decimal("80000"),
        )
        merged = merge_form16(merged, f16)

        # Step 2: Form 26AS
        f26 = ParsedForm26AS(
            total_tds=Decimal("95000"),
            advance_tax_paid=Decimal("20000"),
        )
        merged = merge_form26as(merged, f26)

        # Step 3: AIS
        ais = ParsedAIS(
            salary_income=Decimal("1100000"),  # lower than Form 16
            interest_income=Decimal("45000"),
            dividend_income=Decimal("15000"),
            tds_total=Decimal("85000"),  # should be ignored since 26AS present
        )
        merged = merge_ais(merged, ais)

        # Assertions
        assert merged.pan == "ABCDE1234F"
        assert merged.salary_income == Decimal("1200000")  # max of 12L vs 11L
        assert merged.interest_income == Decimal("45000")
        assert merged.dividend_income == Decimal("15000")
        assert merged.other_income == Decimal("60000")  # 45K + 15K
        assert merged.section_80c == Decimal("150000")
        assert merged.section_80d == Decimal("25000")
        assert merged.section_80ccd_1b == Decimal("50000")
        assert merged.tds_total == Decimal("95000")  # from 26AS, not AIS
        assert merged.advance_tax == Decimal("20000")
        assert sorted(merged.sources) == ["26as", "ais", "form16"]


class TestMergedToITR1Input:
    """Verify conversion from MergedITRData to ITR1Input."""

    def test_basic_conversion(self):
        merged = MergedITRData(
            pan="ABCDE1234F",
            salary_income=Decimal("1200000"),
            interest_income=Decimal("50000"),
            dividend_income=Decimal("10000"),
            section_80c=Decimal("150000"),
            section_80d=Decimal("25000"),
            tds_total=Decimal("80000"),
            advance_tax=Decimal("10000"),
            self_assessment_tax=Decimal("5000"),
        )
        inp = merged_to_itr1_input(merged)
        assert inp.pan == "ABCDE1234F"
        assert inp.salary_income == Decimal("1200000")
        # other_income includes interest + dividend + merged.other_income
        assert inp.other_income == Decimal("60000")  # 0 + 50K + 10K
        assert inp.section_80c == Decimal("150000")
        assert inp.tds_total == Decimal("80000")
        assert inp.advance_tax == Decimal("10000")
        assert inp.self_assessment_tax == Decimal("5000")

    def test_standard_deduction_carried(self):
        merged = MergedITRData(standard_deduction=Decimal("50000"))
        inp = merged_to_itr1_input(merged)
        assert inp.standard_deduction == Decimal("50000")


class TestMergedToITR4Input:
    """Verify conversion from MergedITRData to ITR4Input."""

    def test_basic_conversion(self):
        merged = MergedITRData(
            business_turnover=Decimal("5000000"),
            salary_income=Decimal("200000"),
            section_80c=Decimal("100000"),
            tds_total=Decimal("50000"),
        )
        inp = merged_to_itr4_input(merged)
        assert inp.gross_turnover == Decimal("5000000")
        assert inp.presumptive_rate == Decimal("8")
        assert inp.salary_income == Decimal("200000")
        assert inp.section_80c == Decimal("100000")
        assert inp.tds_total == Decimal("50000")


class TestFormatReviewSummary:
    """Verify formatted review output."""

    def test_contains_all_sections(self):
        merged = MergedITRData(
            salary_income=Decimal("1200000"),
            section_80c=Decimal("150000"),
            tds_total=Decimal("80000"),
            sources=["form16", "26as"],
        )
        output = format_review_summary(merged)
        assert "Extracted Tax Data" in output
        assert "FORM16, 26AS" in output
        assert "INCOME:" in output
        assert "DEDUCTIONS" in output
        assert "TAX PAID:" in output
        assert "1,200,000" in output
        assert "150,000" in output
        assert "80,000" in output

    def test_empty_data(self):
        merged = MergedITRData()
        output = format_review_summary(merged)
        assert "None" in output  # No sources
        assert "Not detected" in output  # No PAN


class TestEditableFields:
    """Verify editable fields mapping covers all relevant fields."""

    def test_all_fields_are_valid_attributes(self):
        merged = MergedITRData()
        for num, (attr, label) in ITR_DOC_EDITABLE_FIELDS.items():
            assert hasattr(merged, attr), f"Field {num} ({attr}) not found on MergedITRData"

    def test_field_count(self):
        assert len(ITR_DOC_EDITABLE_FIELDS) == 15

    def test_labels_are_strings(self):
        for num, (attr, label) in ITR_DOC_EDITABLE_FIELDS.items():
            assert isinstance(label, str)
            assert len(label) > 0


class TestSerialization:
    """Verify serialization/deserialization for Redis session storage."""

    def test_round_trip(self):
        original = MergedITRData(
            salary_income=Decimal("1200000"),
            interest_income=Decimal("50000"),
            section_80c=Decimal("150000"),
            tds_total=Decimal("80000"),
            pan="ABCDE1234F",
            sources=["form16", "26as"],
        )
        data = merged_to_dict(original)
        restored = dict_to_merged(data)

        assert restored.salary_income == original.salary_income
        assert restored.interest_income == original.interest_income
        assert restored.section_80c == original.section_80c
        assert restored.tds_total == original.tds_total
        assert restored.pan == original.pan
        assert restored.sources == original.sources

    def test_empty_dict(self):
        restored = dict_to_merged({})
        assert restored.salary_income == Decimal("0")
        assert restored.sources == []

    def test_none_input(self):
        restored = dict_to_merged(None)
        assert restored.salary_income == Decimal("0")


class TestDictToDataclass:
    """Verify LLM output dict -> typed dataclass conversion."""

    def test_dict_to_form16(self):
        data = {
            "employer_name": "TCS Ltd",
            "gross_salary": 1200000,
            "section_80c": "150000",
            "total_tax_deducted": 80000.50,
            "section_80d": None,
        }
        f16 = dict_to_parsed_form16(data)
        assert f16.employer_name == "TCS Ltd"
        assert f16.gross_salary == Decimal("1200000")
        assert f16.section_80c == Decimal("150000")
        assert f16.total_tax_deducted == Decimal("80000.50")
        assert f16.section_80d is None

    def test_dict_to_form26as(self):
        data = {
            "pan": "ABCDE1234F",
            "total_tds": 95000,
            "advance_tax_paid": 20000,
            "tds_entries": [{"deductor": "TCS", "amount": 95000}],
        }
        f26 = dict_to_parsed_form26as(data)
        assert f26.pan == "ABCDE1234F"
        assert f26.total_tds == Decimal("95000")
        assert len(f26.tds_entries) == 1

    def test_dict_to_ais(self):
        data = {
            "salary_income": 1100000,
            "interest_income": 45000,
            "business_turnover": None,
        }
        ais = dict_to_parsed_ais(data)
        assert ais.salary_income == Decimal("1100000")
        assert ais.interest_income == Decimal("45000")
        assert ais.business_turnover is None

    def test_invalid_decimal_handled(self):
        data = {"gross_salary": "not_a_number"}
        f16 = dict_to_parsed_form16(data)
        assert f16.gross_salary is None
