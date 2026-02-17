# app/api/v1/routes/gst_periods.py
"""
V1 API endpoints for GST return-period management (monthly compliance).

All endpoints require Bearer JWT authentication.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.infrastructure.db.models import User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok, error
from app.api.v1.schemas.periods import (
    PeriodCreateRequest,
    PeriodResponse,
    ReconciliationSummaryResponse,
    LiabilityResponse,
    Import2bResponse,
    MismatchEntry,
    StatusTransitionRequest,
)

logger = logging.getLogger("api.v1.gst_periods")

router = APIRouter(prefix="/gst/periods", tags=["GST Periods"])

_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ============================================================
# Helpers
# ============================================================

def _to_period_response(rp) -> dict:
    """Convert ReturnPeriod ORM to PeriodResponse dict."""
    return PeriodResponse(
        id=str(rp.id),
        user_id=str(rp.user_id),
        gstin=rp.gstin,
        fy=rp.fy,
        period=rp.period,
        status=rp.status,
        outward_count=rp.outward_count or 0,
        inward_count=rp.inward_count or 0,
        output_tax_igst=float(rp.output_tax_igst or 0),
        output_tax_cgst=float(rp.output_tax_cgst or 0),
        output_tax_sgst=float(rp.output_tax_sgst or 0),
        itc_igst=float(rp.itc_igst or 0),
        itc_cgst=float(rp.itc_cgst or 0),
        itc_sgst=float(rp.itc_sgst or 0),
        net_payable_igst=float(rp.net_payable_igst or 0),
        net_payable_cgst=float(rp.net_payable_cgst or 0),
        net_payable_sgst=float(rp.net_payable_sgst or 0),
        rcm_igst=float(rp.rcm_igst or 0),
        rcm_cgst=float(rp.rcm_cgst or 0),
        rcm_sgst=float(rp.rcm_sgst or 0),
        risk_flags=rp.risk_flags,
        computed_at=rp.computed_at.isoformat() if rp.computed_at else None,
    ).model_dump()


# ============================================================
# Endpoints
# ============================================================

@router.post("", summary="Create or get return period")
async def create_period(
    body: PeriodCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or retrieve an existing return period for the authenticated user."""
    if not _GSTIN_RE.match(body.gstin):
        raise HTTPException(status_code=400, detail=f"Invalid GSTIN: {body.gstin}")
    if not _PERIOD_RE.match(body.period):
        raise HTTPException(status_code=400, detail=f"Invalid period: {body.period}")

    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.create_or_get(user.id, body.gstin, body.period)
    return ok(data=_to_period_response(rp))


@router.get("", summary="List return periods")
async def list_periods(
    fy: str | None = Query(None, description="Financial year filter, e.g. 2024-25"),
    limit: int = Query(12, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List return periods for the authenticated user, most recent first."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    periods = await repo.list_for_user(user.id, fy=fy, limit=limit)
    return ok(data=[_to_period_response(p) for p in periods])


@router.get("/{period_id}", summary="Get period detail")
async def get_period(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a specific return period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")
    return ok(data=_to_period_response(rp))


@router.post("/{period_id}/import-2b", summary="Import GSTR-2B")
async def import_2b(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import GSTR-2B data from MasterGST for a period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    from app.domain.services.gstr2b_service import import_gstr2b
    try:
        result = await import_gstr2b(
            user_id=user.id,
            gstin=rp.gstin,
            period=rp.period,
            period_id=period_id,
            db=db,
        )
    except Exception as exc:
        logger.exception("GSTR-2B import failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data=Import2bResponse(
        period=result.period,
        total_entries=result.total_entries,
        supplier_count=result.supplier_count,
        total_taxable=float(result.total_taxable),
        errors=result.errors,
    ).model_dump())


@router.post("/{period_id}/reconcile", summary="Run ITC reconciliation")
async def reconcile(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run ITC reconciliation matching purchase invoices against GSTR-2B."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    from app.domain.services.gst_reconciliation import reconcile_period
    try:
        summary = await reconcile_period(period_id, db)
    except Exception as exc:
        logger.exception("Reconciliation failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data=ReconciliationSummaryResponse(
        total_2b_entries=summary.total_2b_entries,
        total_book_entries=summary.total_book_entries,
        matched=summary.matched,
        value_mismatch=summary.value_mismatch,
        missing_in_2b=summary.missing_in_2b,
        missing_in_books=summary.missing_in_books,
        matched_taxable=float(summary.matched_taxable),
        mismatch_taxable_diff=float(summary.mismatch_taxable_diff),
    ).model_dump())


@router.post("/{period_id}/compute", summary="Compute net liability")
async def compute_liability(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute net GST liability for a period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    from app.domain.services.gst_liability import compute_net_liability
    try:
        comp = await compute_net_liability(period_id, db)
    except Exception as exc:
        logger.exception("Liability computation failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data=LiabilityResponse(
        outward_count=comp.outward_count,
        inward_count=comp.inward_count,
        output_igst=float(comp.output_igst),
        output_cgst=float(comp.output_cgst),
        output_sgst=float(comp.output_sgst),
        itc_igst=float(comp.itc_igst),
        itc_cgst=float(comp.itc_cgst),
        itc_sgst=float(comp.itc_sgst),
        net_igst=float(comp.net_igst),
        net_cgst=float(comp.net_cgst),
        net_sgst=float(comp.net_sgst),
        total_net_payable=float(comp.total_net_payable),
        rcm_igst=float(comp.rcm_igst),
        rcm_cgst=float(comp.rcm_cgst),
        rcm_sgst=float(comp.rcm_sgst),
        risk_flags=comp.risk_flags,
    ).model_dump())


@router.get("/{period_id}/reconciliation", summary="Get reconciliation summary")
async def get_reconciliation(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get reconciliation summary and mismatches for a period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    from app.domain.services.gst_reconciliation import (
        get_reconciliation_summary,
        get_mismatches,
    )

    summary = await get_reconciliation_summary(period_id, db)
    mismatches = await get_mismatches(period_id, db)

    mismatch_list = [
        MismatchEntry(
            id=str(m.id),
            supplier_gstin=m.gstr2b_supplier_gstin,
            invoice_number=m.gstr2b_invoice_number,
            taxable_value=float(m.gstr2b_taxable_value or 0),
            match_status=m.match_status,
            mismatch_details=m.mismatch_details,
        ).model_dump()
        for m in mismatches
    ]

    return ok(data={"summary": summary, "mismatches": mismatch_list})


@router.post("/{period_id}/transition", summary="Transition period status")
async def transition_status(
    period_id: UUID,
    body: StatusTransitionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition a period to a new status (with workflow guards)."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    from app.domain.services.gst_workflow import InvalidPeriodTransitionError

    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    try:
        updated = await repo.update_status(period_id, body.new_status)
    except InvalidPeriodTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ok(data=_to_period_response(updated))


# ============================================================
# Phase 2: Risk Scoring
# ============================================================

@router.post("/{period_id}/risk-score", summary="Compute risk assessment")
async def compute_risk(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute full 100-point risk assessment for a period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    from app.domain.services.gst_risk_scoring import compute_risk_score
    try:
        result = await compute_risk_score(period_id, db)
    except Exception as exc:
        logger.exception("Risk scoring failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data=result.to_dict())


@router.get("/{period_id}/risk-score", summary="Get risk assessment")
async def get_risk(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get existing risk assessment for a period."""
    import json as _json
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    from app.infrastructure.db.repositories.risk_assessment_repository import RiskAssessmentRepository

    rp_repo = ReturnPeriodRepository(db)
    rp = await rp_repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    ra_repo = RiskAssessmentRepository(db)
    ra = await ra_repo.get_by_period(period_id)
    if not ra:
        raise HTTPException(status_code=404, detail="Risk assessment not found. Run POST first.")

    flags = _json.loads(ra.risk_flags) if ra.risk_flags else []
    actions = _json.loads(ra.recommended_actions) if ra.recommended_actions else []

    data = {
        "id": str(ra.id),
        "period_id": str(ra.period_id),
        "risk_score": ra.risk_score,
        "risk_level": ra.risk_level,
        "risk_flags": flags,
        "recommended_actions": actions,
        "category_a_score": ra.category_a_score,
        "category_b_score": ra.category_b_score,
        "category_c_score": ra.category_c_score,
        "category_d_score": ra.category_d_score,
        "category_e_score": ra.category_e_score,
        "ca_override_score": ra.ca_override_score,
        "ca_final_outcome": ra.ca_final_outcome,
        "computed_at": ra.computed_at.isoformat() if ra.computed_at else None,
    }

    # ML scoring fields (Phase 3B)
    if ra.ml_risk_score is not None:
        data["ml_risk_score"] = ra.ml_risk_score
        data["blend_weight"] = ra.blend_weight
        ml_prediction = None
        if ra.ml_prediction_json:
            try:
                ml_prediction = _json.loads(ra.ml_prediction_json)
            except (ValueError, TypeError):
                pass
        data["ml_prediction"] = ml_prediction

    return ok(data=data)


# ============================================================
# Phase 2: Payments
# ============================================================

from app.api.v1.schemas.payment import PaymentCreateRequest

@router.post("/{period_id}/payments", summary="Record a payment")
async def record_payment_v1(
    period_id: UUID,
    body: PaymentCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a challan payment for a period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    from app.domain.services.gst_payment import record_payment as do_record
    from datetime import date as _date

    rp_repo = ReturnPeriodRepository(db)
    rp = await rp_repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    challan_data = body.model_dump()
    if challan_data.get("challan_date"):
        try:
            challan_data["challan_date"] = _date.fromisoformat(challan_data["challan_date"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid challan_date. Use YYYY-MM-DD")

    try:
        payment = await do_record(period_id, challan_data, db)
    except Exception as exc:
        logger.exception("Payment recording failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data={
        "id": str(payment.id),
        "challan_number": payment.challan_number,
        "total": float(payment.total or 0),
        "status": payment.status,
    })


@router.get("/{period_id}/payments", summary="List payments")
async def list_payments_v1(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all payments for a period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    from app.domain.services.gst_payment import get_payment_summary

    rp_repo = ReturnPeriodRepository(db)
    rp = await rp_repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    try:
        summary = await get_payment_summary(period_id, db)
    except Exception as exc:
        logger.exception("Payment summary failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data=summary)


@router.post("/{period_id}/validate-payment", summary="Validate payment vs liability")
async def validate_payment_v1(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate total payments against computed liability."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    from app.domain.services.gst_payment import validate_payment as do_validate

    rp_repo = ReturnPeriodRepository(db)
    rp = await rp_repo.get_by_id(period_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Period not found")

    try:
        result = await do_validate(period_id, db)
    except Exception as exc:
        logger.exception("Payment validation failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data=result.to_dict())
