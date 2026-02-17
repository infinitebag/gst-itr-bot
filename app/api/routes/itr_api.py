# app/api/routes/itr_api.py
"""
REST API endpoints for ITR computation, PDF generation, and JSON export.

These endpoints are designed for mobile/web app integration.
Each endpoint is stateless and self-contained — no WhatsApp session required.
"""

from __future__ import annotations

import io
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.domain.services.itr_service import (
    ITR1Input,
    ITR2Input,
    ITR4Input,
    compute_itr1_dynamic as compute_itr1,
    compute_itr2_dynamic as compute_itr2,
    compute_itr4_dynamic as compute_itr4,
    format_itr_result,
)
from app.domain.services.itr_pdf import generate_itr1_pdf, generate_itr4_pdf
from app.domain.services.itr_json import (
    generate_itr1_json,
    generate_itr4_json,
    itr_json_to_string,
)
from app.infrastructure.db.repositories import FilingRepository

logger = logging.getLogger("itr_api")
router = APIRouter()


# ============================================================
# Request Models
# ============================================================

class ITR1Request(BaseModel):
    """Request body for ITR-1 (Sahaj) computation."""
    pan: str = Field(default="", description="PAN number")
    name: str = Field(default="", description="Taxpayer name")
    assessment_year: str = Field(default="2025-26", description="Assessment year (e.g. 2025-26)")

    salary_income: float = Field(default=0, ge=0, description="Gross salary income")
    standard_deduction: float = Field(default=75000, ge=0, description="Standard deduction u/s 16(ia)")
    house_property_income: float = Field(default=0, description="Net income from house property (can be negative)")
    other_income: float = Field(default=0, ge=0, description="Interest, dividends, etc.")

    section_80c: float = Field(default=0, ge=0, description="PPF, ELSS, LIC, etc. (max 1.5L)")
    section_80d: float = Field(default=0, ge=0, description="Medical insurance premium")
    section_80e: float = Field(default=0, ge=0, description="Education loan interest")
    section_80g: float = Field(default=0, ge=0, description="Donations")
    section_80tta: float = Field(default=0, ge=0, description="Savings interest (max 10K)")
    section_80ccd_1b: float = Field(default=0, ge=0, description="NPS additional (max 50K)")
    other_deductions: float = Field(default=0, ge=0, description="Other Chapter VI-A deductions")

    tds_total: float = Field(default=0, ge=0, description="Total TDS deducted")
    advance_tax: float = Field(default=0, ge=0, description="Advance tax paid")
    self_assessment_tax: float = Field(default=0, ge=0, description="Self-assessment tax paid")


class ITR4Request(BaseModel):
    """Request body for ITR-4 (Sugam) computation."""
    pan: str = Field(default="", description="PAN number")
    name: str = Field(default="", description="Taxpayer name")
    assessment_year: str = Field(default="2025-26", description="Assessment year")

    gross_turnover: float = Field(default=0, ge=0, description="Business turnover u/s 44AD")
    presumptive_rate: float = Field(default=8, ge=0, le=100, description="Presumptive profit rate %")
    gross_receipts: float = Field(default=0, ge=0, description="Professional receipts u/s 44ADA")
    professional_rate: float = Field(default=50, ge=0, le=100, description="Professional profit rate %")

    salary_income: float = Field(default=0, ge=0, description="Salary income (if any)")
    house_property_income: float = Field(default=0, description="HP income (can be negative)")
    other_income: float = Field(default=0, ge=0, description="Other sources income")

    section_80c: float = Field(default=0, ge=0, description="Section 80C deductions")
    section_80d: float = Field(default=0, ge=0, description="Section 80D deductions")
    other_deductions: float = Field(default=0, ge=0, description="Other deductions")

    tds_total: float = Field(default=0, ge=0, description="Total TDS deducted")
    advance_tax: float = Field(default=0, ge=0, description="Advance tax paid")


class ITR2Request(BaseModel):
    """Request body for ITR-2 (Salaried + Capital Gains) computation."""
    pan: str = Field(default="", description="PAN number")
    name: str = Field(default="", description="Taxpayer name")
    dob: str = Field(default="", description="Date of birth DD/MM/YYYY")
    gender: str = Field(default="", description="M/F/O")
    assessment_year: str = Field(default="2025-26", description="Assessment year")

    salary_income: float = Field(default=0, ge=0, description="Gross salary income")
    standard_deduction: float = Field(default=75000, ge=0, description="Standard deduction u/s 16(ia)")
    house_property_income: float = Field(default=0, description="Net income from house property")
    other_income: float = Field(default=0, ge=0, description="Interest, dividends, etc.")

    # Capital Gains (equity)
    stcg_111a: float = Field(default=0, ge=0, description="Short-term CG from equity u/s 111A (taxed at 15%)")
    ltcg_112a: float = Field(default=0, ge=0, description="Long-term CG from equity u/s 112A (10% over 1L)")

    # Deductions
    section_80c: float = Field(default=0, ge=0, description="PPF, ELSS, LIC, etc. (max 1.5L)")
    section_80d: float = Field(default=0, ge=0, description="Medical insurance premium")
    section_80e: float = Field(default=0, ge=0, description="Education loan interest")
    section_80g: float = Field(default=0, ge=0, description="Donations")
    section_80tta: float = Field(default=0, ge=0, description="Savings interest (max 10K)")
    section_80ccd_1b: float = Field(default=0, ge=0, description="NPS additional (max 50K)")
    other_deductions: float = Field(default=0, ge=0, description="Other Chapter VI-A deductions")

    tds_total: float = Field(default=0, ge=0, description="Total TDS deducted")
    advance_tax: float = Field(default=0, ge=0, description="Advance tax paid")
    self_assessment_tax: float = Field(default=0, ge=0, description="Self-assessment tax paid")


# ============================================================
# Response Models
# ============================================================

class TaxBreakdownResponse(BaseModel):
    """Tax computation for a single regime."""
    regime: str
    gross_total_income: float
    total_deductions: float
    taxable_income: float
    tax_on_income: float
    rebate_87a: float
    surcharge: float
    health_cess: float
    total_tax_liability: float
    taxes_paid: float
    tax_payable: float
    slab_details: list[dict]


class ITRComputeResponse(BaseModel):
    """Response from ITR computation."""
    form_type: str = Field(description="ITR-1, ITR-2, or ITR-4")
    old_regime: TaxBreakdownResponse
    new_regime: TaxBreakdownResponse
    recommended_regime: str = Field(description="old or new")
    savings: float = Field(description="Tax savings with recommended regime")
    formatted_text: str = Field(description="WhatsApp-friendly text summary")


# ============================================================
# Helpers
# ============================================================

def _to_itr1_input(req: ITR1Request) -> ITR1Input:
    """Convert API request to ITR1Input dataclass."""
    return ITR1Input(
        pan=req.pan,
        name=req.name,
        assessment_year=req.assessment_year,
        salary_income=Decimal(str(req.salary_income)),
        standard_deduction=Decimal(str(req.standard_deduction)),
        house_property_income=Decimal(str(req.house_property_income)),
        other_income=Decimal(str(req.other_income)),
        section_80c=Decimal(str(req.section_80c)),
        section_80d=Decimal(str(req.section_80d)),
        section_80e=Decimal(str(req.section_80e)),
        section_80g=Decimal(str(req.section_80g)),
        section_80tta=Decimal(str(req.section_80tta)),
        section_80ccd_1b=Decimal(str(req.section_80ccd_1b)),
        other_deductions=Decimal(str(req.other_deductions)),
        tds_total=Decimal(str(req.tds_total)),
        advance_tax=Decimal(str(req.advance_tax)),
        self_assessment_tax=Decimal(str(req.self_assessment_tax)),
    )


def _to_itr4_input(req: ITR4Request) -> ITR4Input:
    """Convert API request to ITR4Input dataclass."""
    return ITR4Input(
        pan=req.pan,
        name=req.name,
        assessment_year=req.assessment_year,
        gross_turnover=Decimal(str(req.gross_turnover)),
        presumptive_rate=Decimal(str(req.presumptive_rate)),
        gross_receipts=Decimal(str(req.gross_receipts)),
        professional_rate=Decimal(str(req.professional_rate)),
        salary_income=Decimal(str(req.salary_income)),
        house_property_income=Decimal(str(req.house_property_income)),
        other_income=Decimal(str(req.other_income)),
        section_80c=Decimal(str(req.section_80c)),
        section_80d=Decimal(str(req.section_80d)),
        other_deductions=Decimal(str(req.other_deductions)),
        tds_total=Decimal(str(req.tds_total)),
        advance_tax=Decimal(str(req.advance_tax)),
    )


def _to_itr2_input(req: ITR2Request) -> ITR2Input:
    """Convert API request to ITR2Input dataclass."""
    return ITR2Input(
        pan=req.pan,
        name=req.name,
        dob=req.dob,
        gender=req.gender,
        assessment_year=req.assessment_year,
        salary_income=Decimal(str(req.salary_income)),
        standard_deduction=Decimal(str(req.standard_deduction)),
        house_property_income=Decimal(str(req.house_property_income)),
        other_income=Decimal(str(req.other_income)),
        stcg_111a=Decimal(str(req.stcg_111a)),
        ltcg_112a=Decimal(str(req.ltcg_112a)),
        section_80c=Decimal(str(req.section_80c)),
        section_80d=Decimal(str(req.section_80d)),
        section_80e=Decimal(str(req.section_80e)),
        section_80g=Decimal(str(req.section_80g)),
        section_80tta=Decimal(str(req.section_80tta)),
        section_80ccd_1b=Decimal(str(req.section_80ccd_1b)),
        other_deductions=Decimal(str(req.other_deductions)),
        tds_total=Decimal(str(req.tds_total)),
        advance_tax=Decimal(str(req.advance_tax)),
        self_assessment_tax=Decimal(str(req.self_assessment_tax)),
    )


def _breakdown_to_response(b) -> TaxBreakdownResponse:
    """Convert TaxBreakdown dataclass to response model."""
    return TaxBreakdownResponse(
        regime=b.regime,
        gross_total_income=float(b.gross_total_income),
        total_deductions=float(b.total_deductions),
        taxable_income=float(b.taxable_income),
        tax_on_income=float(b.tax_on_income),
        rebate_87a=float(b.rebate_87a),
        surcharge=float(b.surcharge),
        health_cess=float(b.health_cess),
        total_tax_liability=float(b.total_tax_liability),
        taxes_paid=float(b.taxes_paid),
        tax_payable=float(b.tax_payable),
        slab_details=b.slab_details,
    )


# ============================================================
# ITR Computation Endpoints
# ============================================================

@router.post("/itr1/compute", response_model=ITRComputeResponse)
async def compute_itr1_api(req: ITR1Request) -> ITRComputeResponse:
    """
    Compute ITR-1 (Sahaj) tax for salaried individuals.

    Compares Old vs New regime and recommends the optimal one.
    No database or login required — pure computation.
    """
    try:
        inp = _to_itr1_input(req)
        result = await compute_itr1(inp)
    except Exception as e:
        logger.exception("ITR-1 computation failed")
        raise HTTPException(status_code=422, detail=f"Computation error: {str(e)}")

    return ITRComputeResponse(
        form_type=result.form_type,
        old_regime=_breakdown_to_response(result.old_regime),
        new_regime=_breakdown_to_response(result.new_regime),
        recommended_regime=result.recommended_regime,
        savings=float(result.savings),
        formatted_text=format_itr_result(result),
    )


@router.post("/itr4/compute", response_model=ITRComputeResponse)
async def compute_itr4_api(req: ITR4Request) -> ITRComputeResponse:
    """
    Compute ITR-4 (Sugam) tax for presumptive income.

    Supports 44AD (business) and 44ADA (profession).
    No database or login required — pure computation.
    """
    try:
        inp = _to_itr4_input(req)
        result = await compute_itr4(inp)
    except Exception as e:
        logger.exception("ITR-4 computation failed")
        raise HTTPException(status_code=422, detail=f"Computation error: {str(e)}")

    return ITRComputeResponse(
        form_type=result.form_type,
        old_regime=_breakdown_to_response(result.old_regime),
        new_regime=_breakdown_to_response(result.new_regime),
        recommended_regime=result.recommended_regime,
        savings=float(result.savings),
        formatted_text=format_itr_result(result),
    )


@router.post("/itr2/compute", response_model=ITRComputeResponse)
async def compute_itr2_api(req: ITR2Request) -> ITRComputeResponse:
    """
    Compute ITR-2 tax for salaried individuals with capital gains.

    Handles equity STCG u/s 111A (15%) and LTCG u/s 112A (10% over 1L).
    Compares Old vs New regime and recommends the optimal one.
    No database or login required — pure computation.
    """
    try:
        inp = _to_itr2_input(req)
        result = await compute_itr2(inp)
    except Exception as e:
        logger.exception("ITR-2 computation failed")
        raise HTTPException(status_code=422, detail=f"Computation error: {str(e)}")

    return ITRComputeResponse(
        form_type=result.form_type,
        old_regime=_breakdown_to_response(result.old_regime),
        new_regime=_breakdown_to_response(result.new_regime),
        recommended_regime=result.recommended_regime,
        savings=float(result.savings),
        formatted_text=format_itr_result(result),
    )


# ============================================================
# ITR PDF Download Endpoints
# ============================================================

@router.post("/itr1/pdf")
async def download_itr1_pdf(req: ITR1Request) -> StreamingResponse:
    """
    Compute ITR-1 and return the result as a downloadable PDF.

    Returns a professional computation sheet with income details,
    deductions, and Old vs New regime comparison.
    """
    try:
        inp = _to_itr1_input(req)
        result = await compute_itr1(inp)
        pdf_bytes = generate_itr1_pdf(inp, result)
    except Exception as e:
        logger.exception("ITR-1 PDF generation failed")
        raise HTTPException(status_code=422, detail=f"PDF generation error: {str(e)}")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=ITR1_computation.pdf",
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.post("/itr4/pdf")
async def download_itr4_pdf(req: ITR4Request) -> StreamingResponse:
    """
    Compute ITR-4 and return the result as a downloadable PDF.
    """
    try:
        inp = _to_itr4_input(req)
        result = await compute_itr4(inp)
        pdf_bytes = generate_itr4_pdf(inp, result)
    except Exception as e:
        logger.exception("ITR-4 PDF generation failed")
        raise HTTPException(status_code=422, detail=f"PDF generation error: {str(e)}")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=ITR4_computation.pdf",
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# ============================================================
# ITR JSON Download Endpoints
# ============================================================

@router.post("/itr1/json")
async def download_itr1_json(req: ITR1Request) -> dict:
    """
    Compute ITR-1 and return structured JSON suitable for
    filing systems or downstream integrations.
    """
    try:
        inp = _to_itr1_input(req)
        result = await compute_itr1(inp)
        return generate_itr1_json(inp, result)
    except Exception as e:
        logger.exception("ITR-1 JSON generation failed")
        raise HTTPException(status_code=422, detail=f"JSON generation error: {str(e)}")


@router.post("/itr4/json")
async def download_itr4_json(req: ITR4Request) -> dict:
    """
    Compute ITR-4 and return structured JSON suitable for
    filing systems or downstream integrations.
    """
    try:
        inp = _to_itr4_input(req)
        result = await compute_itr4(inp)
        return generate_itr4_json(inp, result)
    except Exception as e:
        logger.exception("ITR-4 JSON generation failed")
        raise HTTPException(status_code=422, detail=f"JSON generation error: {str(e)}")


# ============================================================
# ITR Filing Record (save to DB for history tracking)
# ============================================================

@router.post("/itr/save-filing")
async def save_itr_filing(
    user_id: str = Query(..., description="User ID to save filing for"),
    form_type: str = Query(..., description="ITR-1 or ITR-4"),
    pan: str = Query("", description="PAN number"),
    assessment_year: str = Query("2025-26", description="Assessment year"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Save an ITR filing record to the database for history tracking.

    Call this after a successful compute + download to track that
    the user has generated their ITR documents.
    """
    if form_type not in ("ITR-1", "ITR-2", "ITR-4"):
        raise HTTPException(status_code=400, detail="form_type must be ITR-1, ITR-2, or ITR-4")

    filing_repo = FilingRepository(db)
    record = await filing_repo.create_record(
        user_id=user_id,
        filing_type="ITR",
        form_type=form_type,
        period=assessment_year,
        pan=pan or None,
        status="generated",
    )

    return {
        "id": str(record.id),
        "filing_type": "ITR",
        "form_type": form_type,
        "period": assessment_year,
        "status": "generated",
        "created_at": record.created_at.isoformat(),
    }
