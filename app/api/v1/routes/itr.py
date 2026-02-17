# app/api/v1/routes/itr.py
"""
ITR computation endpoints: ITR-1 (Sahaj), ITR-2 (Capital Gains), and ITR-4 (Sugam).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.infrastructure.db.models import User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok
from app.api.v1.schemas.itr import (
    ITR1Request,
    ITR2Request,
    ITR4Request,
    ITRResultResponse,
    TaxBreakdownSchema,
)

logger = logging.getLogger("api.v1.itr")

router = APIRouter(prefix="/itr", tags=["ITR"])


def _breakdown_to_schema(bd) -> TaxBreakdownSchema:
    """Convert a service-layer TaxBreakdown dataclass to a response schema."""
    return TaxBreakdownSchema(
        regime=bd.regime,
        gross_total_income=bd.gross_total_income,
        total_deductions=bd.total_deductions,
        taxable_income=bd.taxable_income,
        tax_on_income=bd.tax_on_income,
        surcharge=bd.surcharge,
        health_cess=bd.health_cess,
        total_tax_liability=bd.total_tax_liability,
        rebate_87a=bd.rebate_87a,
        tax_after_rebate=bd.tax_after_rebate,
        taxes_paid=bd.taxes_paid,
        tax_payable=bd.tax_payable,
        slab_details=bd.slab_details,
    )


@router.post("/itr1", response_model=dict)
async def compute_itr1(body: ITR1Request, user: User = Depends(get_current_user)):
    """
    Compute ITR-1 (Sahaj) with old vs new regime comparison.

    Returns tax breakdowns for both regimes and a recommendation.
    """
    from app.domain.services.itr_service import compute_itr1_dynamic, ITR1Input

    inp = ITR1Input(
        pan=body.pan,
        name=body.name,
        assessment_year=body.assessment_year,
        salary_income=body.salary_income,
        standard_deduction=body.standard_deduction,
        house_property_income=body.house_property_income,
        other_income=body.other_income,
        agricultural_income=body.agricultural_income,
        section_80c=body.section_80c,
        section_80d=body.section_80d,
        section_80e=body.section_80e,
        section_80g=body.section_80g,
        section_80tta=body.section_80tta,
        section_80ccd_1b=body.section_80ccd_1b,
        other_deductions=body.other_deductions,
        tds_total=body.tds_total,
        advance_tax=body.advance_tax,
        self_assessment_tax=body.self_assessment_tax,
    )
    result = await compute_itr1_dynamic(inp)

    resp = ITRResultResponse(
        form_type=result.form_type,
        old_regime=_breakdown_to_schema(result.old_regime) if result.old_regime else None,
        new_regime=_breakdown_to_schema(result.new_regime) if result.new_regime else None,
        recommended_regime=result.recommended_regime,
        savings=result.savings,
    )

    return ok(data=resp.model_dump())


@router.post("/itr4", response_model=dict)
async def compute_itr4(body: ITR4Request, user: User = Depends(get_current_user)):
    """
    Compute ITR-4 (Sugam) for presumptive taxation.

    Returns tax breakdowns for both regimes and a recommendation.
    """
    from app.domain.services.itr_service import compute_itr4_dynamic, ITR4Input

    inp = ITR4Input(
        pan=body.pan,
        name=body.name,
        assessment_year=body.assessment_year,
        gross_turnover=body.gross_turnover,
        presumptive_rate=body.presumptive_rate,
        gross_receipts=body.gross_receipts,
        professional_rate=body.professional_rate,
        salary_income=body.salary_income,
        house_property_income=body.house_property_income,
        other_income=body.other_income,
        section_80c=body.section_80c,
        section_80d=body.section_80d,
        other_deductions=body.other_deductions,
        tds_total=body.tds_total,
        advance_tax=body.advance_tax,
    )
    result = await compute_itr4_dynamic(inp)

    resp = ITRResultResponse(
        form_type=result.form_type,
        old_regime=_breakdown_to_schema(result.old_regime) if result.old_regime else None,
        new_regime=_breakdown_to_schema(result.new_regime) if result.new_regime else None,
        recommended_regime=result.recommended_regime,
        savings=result.savings,
    )

    return ok(data=resp.model_dump())


@router.post("/itr2", response_model=dict)
async def compute_itr2_endpoint(body: ITR2Request, user: User = Depends(get_current_user)):
    """
    Compute ITR-2 for salaried individuals with capital gains.

    Handles equity STCG u/s 111A (15%) and LTCG u/s 112A (10% over 1L).
    Returns tax breakdowns for both regimes and a recommendation.
    """
    from app.domain.services.itr_service import compute_itr2_dynamic, ITR2Input

    inp = ITR2Input(
        pan=body.pan,
        name=body.name,
        dob=body.dob,
        gender=body.gender,
        assessment_year=body.assessment_year,
        salary_income=body.salary_income,
        standard_deduction=body.standard_deduction,
        house_property_income=body.house_property_income,
        other_income=body.other_income,
        stcg_111a=body.stcg_111a,
        ltcg_112a=body.ltcg_112a,
        section_80c=body.section_80c,
        section_80d=body.section_80d,
        section_80e=body.section_80e,
        section_80g=body.section_80g,
        section_80tta=body.section_80tta,
        section_80ccd_1b=body.section_80ccd_1b,
        other_deductions=body.other_deductions,
        tds_total=body.tds_total,
        advance_tax=body.advance_tax,
        self_assessment_tax=body.self_assessment_tax,
    )
    result = await compute_itr2_dynamic(inp)

    resp = ITRResultResponse(
        form_type=result.form_type,
        old_regime=_breakdown_to_schema(result.old_regime) if result.old_regime else None,
        new_regime=_breakdown_to_schema(result.new_regime) if result.new_regime else None,
        recommended_regime=result.recommended_regime,
        savings=result.savings,
    )

    return ok(data=resp.model_dump())
