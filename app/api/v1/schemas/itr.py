# app/api/v1/schemas/itr.py
"""Request and response schemas for ITR endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ITR-1 (Sahaj) — Salaried individuals
# ---------------------------------------------------------------------------

class ITR1Request(BaseModel):
    pan: str = Field(default="XXXXX0000X", max_length=10)
    name: str = Field(default="API User", max_length=255)
    assessment_year: str = Field(default="2025-26", description="e.g. 2025-26 (FY 2024-25)")

    salary_income: Decimal = Field(default=Decimal("0"), ge=0)
    standard_deduction: Decimal = Field(default=Decimal("75000"), ge=0, description="Section 16(ia) — Rs 75,000 for AY 2025-26")
    house_property_income: Decimal = Field(default=Decimal("0"))
    other_income: Decimal = Field(default=Decimal("0"), ge=0)
    agricultural_income: Decimal = Field(default=Decimal("0"), ge=0)

    # Deductions (old regime — Chapter VI-A)
    section_80c: Decimal = Field(default=Decimal("0"), ge=0, description="PPF, ELSS, LIC, etc. (max 1.5L)")
    section_80d: Decimal = Field(default=Decimal("0"), ge=0, description="Medical insurance (max 25K/50K/1L)")
    section_80e: Decimal = Field(default=Decimal("0"), ge=0, description="Education loan interest (no limit)")
    section_80g: Decimal = Field(default=Decimal("0"), ge=0, description="Donations")
    section_80tta: Decimal = Field(default=Decimal("0"), ge=0, description="Savings account interest (max 10K)")
    section_80ccd_1b: Decimal = Field(default=Decimal("0"), ge=0, description="NPS additional (max 50K)")
    other_deductions: Decimal = Field(default=Decimal("0"), ge=0)

    # Taxes already paid
    tds_total: Decimal = Field(default=Decimal("0"), ge=0)
    advance_tax: Decimal = Field(default=Decimal("0"), ge=0)
    self_assessment_tax: Decimal = Field(default=Decimal("0"), ge=0)


# ---------------------------------------------------------------------------
# ITR-4 (Sugam) — Presumptive taxation
# ---------------------------------------------------------------------------

class ITR4Request(BaseModel):
    pan: str = Field(default="XXXXX0000X", max_length=10)
    name: str = Field(default="API User", max_length=255)
    assessment_year: str = Field(default="2025-26", description="e.g. 2025-26 (FY 2024-25)")

    gross_turnover: Decimal = Field(default=Decimal("0"), ge=0)
    presumptive_rate: Decimal = Field(default=Decimal("8"), ge=0, le=100)

    gross_receipts: Decimal = Field(default=Decimal("0"), ge=0)
    professional_rate: Decimal = Field(default=Decimal("50"), ge=0, le=100)

    salary_income: Decimal = Field(default=Decimal("0"), ge=0)
    house_property_income: Decimal = Field(default=Decimal("0"))
    other_income: Decimal = Field(default=Decimal("0"), ge=0)

    section_80c: Decimal = Field(default=Decimal("0"), ge=0)
    section_80d: Decimal = Field(default=Decimal("0"), ge=0)
    other_deductions: Decimal = Field(default=Decimal("0"), ge=0)

    tds_total: Decimal = Field(default=Decimal("0"), ge=0)
    advance_tax: Decimal = Field(default=Decimal("0"), ge=0)


# ---------------------------------------------------------------------------
# ITR-2 — Salaried + Capital Gains (equity)
# ---------------------------------------------------------------------------

class ITR2Request(BaseModel):
    pan: str = Field(default="XXXXX0000X", max_length=10)
    name: str = Field(default="API User", max_length=255)
    dob: str = Field(default="", description="Date of birth DD/MM/YYYY")
    gender: str = Field(default="", description="M/F/O")
    assessment_year: str = Field(default="2025-26", description="e.g. 2025-26 (FY 2024-25)")

    salary_income: Decimal = Field(default=Decimal("0"), ge=0)
    standard_deduction: Decimal = Field(default=Decimal("75000"), ge=0, description="Section 16(ia) — Rs 75,000 for AY 2025-26")
    house_property_income: Decimal = Field(default=Decimal("0"))
    other_income: Decimal = Field(default=Decimal("0"), ge=0)

    # Capital Gains (equity — Phase 1)
    stcg_111a: Decimal = Field(default=Decimal("0"), ge=0, description="Short-term CG from equity u/s 111A (taxed at 15%)")
    ltcg_112a: Decimal = Field(default=Decimal("0"), ge=0, description="Long-term CG from equity u/s 112A (10% over 1L)")

    # Deductions (old regime — Chapter VI-A)
    section_80c: Decimal = Field(default=Decimal("0"), ge=0, description="PPF, ELSS, LIC, etc. (max 1.5L)")
    section_80d: Decimal = Field(default=Decimal("0"), ge=0, description="Medical insurance (max 25K/50K/1L)")
    section_80e: Decimal = Field(default=Decimal("0"), ge=0, description="Education loan interest (no limit)")
    section_80g: Decimal = Field(default=Decimal("0"), ge=0, description="Donations")
    section_80tta: Decimal = Field(default=Decimal("0"), ge=0, description="Savings account interest (max 10K)")
    section_80ccd_1b: Decimal = Field(default=Decimal("0"), ge=0, description="NPS additional (max 50K)")
    other_deductions: Decimal = Field(default=Decimal("0"), ge=0)

    # Taxes already paid
    tds_total: Decimal = Field(default=Decimal("0"), ge=0)
    advance_tax: Decimal = Field(default=Decimal("0"), ge=0)
    self_assessment_tax: Decimal = Field(default=Decimal("0"), ge=0)


# ---------------------------------------------------------------------------
# ITR Result (shared response for ITR-1, ITR-2, and ITR-4)
# ---------------------------------------------------------------------------

class SlabDetail(BaseModel):
    range: str
    rate: str
    tax: Decimal


class TaxBreakdownSchema(BaseModel):
    regime: str
    gross_total_income: Decimal
    total_deductions: Decimal
    taxable_income: Decimal
    tax_on_income: Decimal
    surcharge: Decimal
    health_cess: Decimal
    total_tax_liability: Decimal
    rebate_87a: Decimal
    tax_after_rebate: Decimal
    taxes_paid: Decimal
    tax_payable: Decimal
    slab_details: list[dict]


class ITRResultResponse(BaseModel):
    form_type: str
    old_regime: TaxBreakdownSchema | None = None
    new_regime: TaxBreakdownSchema | None = None
    recommended_regime: str
    savings: Decimal
