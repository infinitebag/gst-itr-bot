"""Tests for the supporting document checklist generator."""

from decimal import Decimal

import pytest

from app.domain.services.itr_form_parser import MergedITRData
from app.domain.services.document_checklist import (
    ChecklistItem,
    DocumentChecklist,
    generate_checklist,
    format_checklist,
    checklist_to_dict,
    dict_to_checklist,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def salaried_merged():
    """Typical salaried individual with some deductions."""
    return MergedITRData(
        salary_income=Decimal("1200000"),
        section_80c=Decimal("150000"),
        section_80d=Decimal("25000"),
        tds_total=Decimal("80000"),
        sources=["form16", "26as"],
    )


@pytest.fixture
def business_merged():
    """Business user with turnover."""
    return MergedITRData(
        business_turnover=Decimal("5000000"),
        advance_tax=Decimal("50000"),
        self_assessment_tax=Decimal("10000"),
        sources=["ais"],
    )


@pytest.fixture
def minimal_merged():
    """Minimal data with no income or deductions."""
    return MergedITRData()


# ---------------------------------------------------------------------------
# generate_checklist tests
# ---------------------------------------------------------------------------

class TestGenerateChecklist:

    def test_salaried_has_form16(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        form16_items = [i for i in cl.items if i.document == "Form 16"]
        assert len(form16_items) == 1
        assert form16_items[0].status == "uploaded"
        assert form16_items[0].priority == "required"

    def test_form26as_always_present(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        f26_items = [i for i in cl.items if i.document == "Form 26AS"]
        assert len(f26_items) == 1
        assert f26_items[0].status == "uploaded"

    def test_ais_always_present(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        ais_items = [i for i in cl.items if "AIS" in i.document]
        assert len(ais_items) == 1
        # Not in sources so should be recommended, not uploaded
        assert ais_items[0].status == "recommended"

    def test_80c_investment_proofs(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        items_80c = [i for i in cl.items if "80C" in i.document]
        assert len(items_80c) == 1
        assert items_80c[0].priority == "recommended"

    def test_80d_health_insurance(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        items_80d = [i for i in cl.items if "80D" in i.document]
        assert len(items_80d) == 1

    def test_no_80c_when_zero(self, minimal_merged):
        cl = generate_checklist(minimal_merged)
        items_80c = [i for i in cl.items if "80C" in i.document]
        assert len(items_80c) == 0

    def test_no_form16_when_no_salary(self, minimal_merged):
        cl = generate_checklist(minimal_merged)
        form16_items = [i for i in cl.items if i.document == "Form 16"]
        assert len(form16_items) == 0

    def test_business_gst_returns(self, business_merged):
        cl = generate_checklist(business_merged)
        gst_items = [i for i in cl.items if "GST" in i.document]
        assert len(gst_items) == 1

    def test_business_bank_statements(self, business_merged):
        cl = generate_checklist(business_merged)
        bank_items = [i for i in cl.items if "Bank" in i.document]
        assert len(bank_items) == 1

    def test_advance_tax_challans(self, business_merged):
        cl = generate_checklist(business_merged)
        adv_items = [i for i in cl.items if "Advance Tax" in i.document]
        assert len(adv_items) == 1
        assert adv_items[0].priority == "required"

    def test_self_assessment_tax_challans(self, business_merged):
        cl = generate_checklist(business_merged)
        sa_items = [i for i in cl.items if "Self-Assessment" in i.document]
        assert len(sa_items) == 1
        assert sa_items[0].priority == "required"

    def test_section_80e(self):
        merged = MergedITRData(section_80e=Decimal("40000"))
        cl = generate_checklist(merged)
        items = [i for i in cl.items if "80E" in i.document]
        assert len(items) == 1

    def test_section_80g(self):
        merged = MergedITRData(section_80g=Decimal("10000"))
        cl = generate_checklist(merged)
        items = [i for i in cl.items if "80G" in i.document]
        assert len(items) == 1

    def test_section_80ccd_1b(self):
        merged = MergedITRData(section_80ccd_1b=Decimal("50000"))
        cl = generate_checklist(merged)
        items = [i for i in cl.items if "80CCD" in i.document]
        assert len(items) == 1

    def test_house_property(self):
        merged = MergedITRData(house_property_income=Decimal("-200000"))
        cl = generate_checklist(merged)
        items = [i for i in cl.items if "Housing Loan" in i.document]
        assert len(items) == 1

    def test_house_property_zero_no_item(self):
        merged = MergedITRData(house_property_income=Decimal("0"))
        cl = generate_checklist(merged)
        items = [i for i in cl.items if "Housing Loan" in i.document]
        assert len(items) == 0

    def test_uploaded_docs_override_sources(self):
        merged = MergedITRData(salary_income=Decimal("1000000"), sources=[])
        cl = generate_checklist(merged, uploaded_docs=["form16", "26as", "ais"])
        form16_items = [i for i in cl.items if i.document == "Form 16"]
        assert form16_items[0].status == "uploaded"
        f26_items = [i for i in cl.items if i.document == "Form 26AS"]
        assert f26_items[0].status == "uploaded"
        ais_items = [i for i in cl.items if "AIS" in i.document]
        assert ais_items[0].status == "uploaded"


class TestChecklistCounts:

    def test_uploaded_count(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        actually_uploaded = sum(1 for i in cl.items if i.status == "uploaded")
        assert cl.uploaded_count == actually_uploaded

    def test_missing_required_count(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        actually_missing_req = sum(1 for i in cl.items if i.status == "missing" and i.priority == "required")
        assert cl.missing_required == actually_missing_req

    def test_missing_recommended_count(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        actually_missing_rec = sum(1 for i in cl.items if i.status != "uploaded" and i.priority == "recommended")
        assert cl.missing_recommended == actually_missing_rec

    def test_empty_data_counts(self, minimal_merged):
        cl = generate_checklist(minimal_merged)
        # Only Form 26AS (required) and AIS (recommended) should be present
        assert cl.missing_required >= 1
        assert cl.uploaded_count == 0


# ---------------------------------------------------------------------------
# format_checklist tests
# ---------------------------------------------------------------------------

class TestFormatChecklist:

    def test_empty_checklist(self):
        cl = DocumentChecklist()
        text = format_checklist(cl)
        assert "No documents required" in text

    def test_formatted_output_contains_markers(self, salaried_merged):
        cl = generate_checklist(salaried_merged)
        text = format_checklist(cl)
        assert "Document Checklist" in text
        assert "[OK]" in text  # uploaded items
        assert "Uploaded:" in text

    def test_missing_required_marker(self):
        merged = MergedITRData(salary_income=Decimal("1000000"))
        cl = generate_checklist(merged)
        text = format_checklist(cl)
        assert "[MISSING]" in text


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------

class TestChecklistSerialization:

    def test_roundtrip(self, salaried_merged):
        original = generate_checklist(salaried_merged)
        d = checklist_to_dict(original)
        restored = dict_to_checklist(d)
        assert len(restored.items) == len(original.items)
        assert restored.uploaded_count == original.uploaded_count
        assert restored.missing_required == original.missing_required

    def test_dict_to_checklist_empty(self):
        cl = dict_to_checklist({})
        assert cl.items == []

    def test_dict_to_checklist_none(self):
        cl = dict_to_checklist(None)
        assert cl.items == []

    def test_item_fields_preserved(self, salaried_merged):
        original = generate_checklist(salaried_merged)
        d = checklist_to_dict(original)
        restored = dict_to_checklist(d)
        for orig_item, rest_item in zip(original.items, restored.items):
            assert orig_item.document == rest_item.document
            assert orig_item.status == rest_item.status
            assert orig_item.priority == rest_item.priority
