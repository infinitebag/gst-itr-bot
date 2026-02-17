# app/api/routes/gst_periods.py
"""
REST API routes for GST return-period management (monthly compliance).

Endpoints for creating periods, importing GSTR-2B, running ITC reconciliation,
computing net liability, and managing period status transitions.

Uses query-param auth (legacy pattern, parallel to gst_mastergst.py).
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db

logger = logging.getLogger("gst_periods")
router = APIRouter()

# GSTIN regex
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ============================================================
# Pydantic models
# ============================================================

class PeriodCreateRequest(BaseModel):
    user_id: str = Field(description="User UUID")
    gstin: str = Field(description="15-char GSTIN")
    period: str = Field(description="Period YYYY-MM, e.g. 2025-01")


class PeriodResponse(BaseModel):
    id: str
    user_id: str
    gstin: str
    fy: str
    period: str
    status: str
    outward_count: int = 0
    inward_count: int = 0
    output_tax_igst: float = 0
    output_tax_cgst: float = 0
    output_tax_sgst: float = 0
    itc_igst: float = 0
    itc_cgst: float = 0
    itc_sgst: float = 0
    net_payable_igst: float = 0
    net_payable_cgst: float = 0
    net_payable_sgst: float = 0
    rcm_igst: float = 0
    rcm_cgst: float = 0
    rcm_sgst: float = 0
    risk_flags: str | None = None
    computed_at: str | None = None


class StatusTransitionRequest(BaseModel):
    new_status: str = Field(description="Target status")


class Import2bRequest(BaseModel):
    user_id: str = Field(description="User UUID")
    gstin: str = Field(description="15-char GSTIN")


# ============================================================
# Helpers
# ============================================================

def _period_to_response(rp: Any) -> dict:
    """Convert ReturnPeriod ORM to response dict."""
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


def _validate_gstin(gstin: str) -> None:
    if not _GSTIN_RE.match(gstin):
        raise HTTPException(status_code=400, detail=f"Invalid GSTIN: {gstin}")


def _validate_period(period: str) -> None:
    if not _PERIOD_RE.match(period):
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}. Expected YYYY-MM")


# ============================================================
# Endpoints
# ============================================================

@router.post("/periods", summary="Create or get return period")
async def create_period(
    body: PeriodCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create or retrieve an existing return period for (gstin, period)."""
    _validate_gstin(body.gstin)
    _validate_period(body.period)

    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.create_or_get(UUID(body.user_id), body.gstin, body.period)
    return {"status": "ok", "data": _period_to_response(rp)}


@router.get("/periods", summary="List return periods for user")
async def list_periods(
    user_id: str = Query(..., description="User UUID"),
    fy: str | None = Query(None, description="Financial year filter, e.g. 2024-25"),
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """List return periods for a user, most recent first."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    periods = await repo.list_for_user(UUID(user_id), fy=fy, limit=limit)
    return {
        "status": "ok",
        "data": [_period_to_response(p) for p in periods],
    }


@router.get("/periods/{period_id}", summary="Get period detail")
async def get_period(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a specific return period."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp:
        raise HTTPException(status_code=404, detail="Period not found")
    return {"status": "ok", "data": _period_to_response(rp)}


@router.post("/periods/{period_id}/import-2b", summary="Import GSTR-2B")
async def import_gstr2b(
    period_id: UUID,
    body: Import2bRequest,
    db: AsyncSession = Depends(get_db),
):
    """Import GSTR-2B data from MasterGST for a period."""
    _validate_gstin(body.gstin)

    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp:
        raise HTTPException(status_code=404, detail="Period not found")

    from app.domain.services.gstr2b_service import import_gstr2b as do_import
    try:
        result = await do_import(
            user_id=UUID(body.user_id),
            gstin=body.gstin,
            period=rp.period,
            period_id=period_id,
            db=db,
        )
    except Exception as exc:
        logger.exception("GSTR-2B import failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "ok",
        "data": {
            "period": result.period,
            "total_entries": result.total_entries,
            "supplier_count": result.supplier_count,
            "total_taxable": float(result.total_taxable),
            "errors": result.errors,
        },
    }


@router.post("/periods/{period_id}/reconcile", summary="Run ITC reconciliation")
async def reconcile(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Run ITC reconciliation matching purchase invoices against GSTR-2B."""
    from app.domain.services.gst_reconciliation import reconcile_period
    try:
        summary = await reconcile_period(period_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Reconciliation failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "ok",
        "data": {
            "total_2b_entries": summary.total_2b_entries,
            "total_book_entries": summary.total_book_entries,
            "matched": summary.matched,
            "value_mismatch": summary.value_mismatch,
            "missing_in_2b": summary.missing_in_2b,
            "missing_in_books": summary.missing_in_books,
            "matched_taxable": float(summary.matched_taxable),
            "mismatch_taxable_diff": float(summary.mismatch_taxable_diff),
        },
    }


@router.post("/periods/{period_id}/compute", summary="Compute net liability")
async def compute_liability(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Compute net GST liability for a period."""
    from app.domain.services.gst_liability import compute_net_liability
    try:
        comp = await compute_net_liability(period_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Liability computation failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "ok",
        "data": {
            "outward_count": comp.outward_count,
            "inward_count": comp.inward_count,
            "output_igst": float(comp.output_igst),
            "output_cgst": float(comp.output_cgst),
            "output_sgst": float(comp.output_sgst),
            "itc_igst": float(comp.itc_igst),
            "itc_cgst": float(comp.itc_cgst),
            "itc_sgst": float(comp.itc_sgst),
            "net_igst": float(comp.net_igst),
            "net_cgst": float(comp.net_cgst),
            "net_sgst": float(comp.net_sgst),
            "total_net_payable": float(comp.total_net_payable),
            "rcm_igst": float(comp.rcm_igst),
            "rcm_cgst": float(comp.rcm_cgst),
            "rcm_sgst": float(comp.rcm_sgst),
            "risk_flags": comp.risk_flags,
        },
    }


@router.get("/periods/{period_id}/reconciliation", summary="Get reconciliation summary")
async def get_reconciliation(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get reconciliation summary and mismatches for a period."""
    from app.domain.services.gst_reconciliation import (
        get_reconciliation_summary,
        get_mismatches,
    )

    summary = await get_reconciliation_summary(period_id, db)
    mismatches = await get_mismatches(period_id, db)

    mismatch_list = []
    for m in mismatches:
        mismatch_list.append({
            "id": str(m.id),
            "supplier_gstin": m.gstr2b_supplier_gstin,
            "invoice_number": m.gstr2b_invoice_number,
            "taxable_value": float(m.gstr2b_taxable_value or 0),
            "match_status": m.match_status,
            "mismatch_details": m.mismatch_details,
        })

    return {
        "status": "ok",
        "data": {
            "summary": summary,
            "mismatches": mismatch_list,
        },
    }


@router.post("/periods/{period_id}/transition", summary="Transition period status")
async def transition_status(
    period_id: UUID,
    body: StatusTransitionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Transition a period to a new status (with workflow guards)."""
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
    from app.domain.services.gst_workflow import InvalidPeriodTransitionError

    repo = ReturnPeriodRepository(db)
    try:
        rp = await repo.update_status(period_id, body.new_status)
    except InvalidPeriodTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not rp:
        raise HTTPException(status_code=404, detail="Period not found")

    return {"status": "ok", "data": _period_to_response(rp)}


# ============================================================
# Phase 2: Risk Scoring Endpoints
# ============================================================

@router.post("/periods/{period_id}/risk-score", summary="Compute risk assessment")
async def compute_risk(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Compute full 100-point risk assessment for a period."""
    from app.domain.services.gst_risk_scoring import compute_risk_score
    try:
        result = await compute_risk_score(period_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Risk scoring failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", "data": result.to_dict()}


@router.get("/periods/{period_id}/risk-score", summary="Get risk assessment")
async def get_risk(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get existing risk assessment for a period."""
    from app.infrastructure.db.repositories.risk_assessment_repository import RiskAssessmentRepository
    import json as _json

    repo = RiskAssessmentRepository(db)
    ra = await repo.get_by_period(period_id)
    if not ra:
        raise HTTPException(status_code=404, detail="Risk assessment not found. Run POST first.")

    flags = []
    if ra.risk_flags:
        try:
            flags = _json.loads(ra.risk_flags)
        except (ValueError, TypeError):
            pass

    actions = []
    if ra.recommended_actions:
        try:
            actions = _json.loads(ra.recommended_actions)
        except (ValueError, TypeError):
            pass

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

    return {"status": "ok", "data": data}


# ============================================================
# Phase 2: Payment Endpoints
# ============================================================

class PaymentCreateBody(BaseModel):
    challan_number: str | None = None
    challan_date: str | None = None
    igst: float = 0
    cgst: float = 0
    sgst: float = 0
    cess: float = 0
    total: float = 0
    payment_mode: str | None = None
    bank_reference: str | None = None
    notes: str | None = None


@router.post("/periods/{period_id}/payments", summary="Record a payment")
async def record_payment_endpoint(
    period_id: UUID,
    body: PaymentCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """Record a challan payment for a period."""
    from app.domain.services.gst_payment import record_payment as do_record
    from datetime import date as _date

    challan_data = body.model_dump()
    if challan_data.get("challan_date"):
        try:
            challan_data["challan_date"] = _date.fromisoformat(challan_data["challan_date"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid challan_date format. Use YYYY-MM-DD")

    try:
        payment = await do_record(period_id, challan_data, db)
    except Exception as exc:
        logger.exception("Payment recording failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "ok",
        "data": {
            "id": str(payment.id),
            "challan_number": payment.challan_number,
            "total": float(payment.total or 0),
            "status": payment.status,
        },
    }


@router.get("/periods/{period_id}/payments", summary="List payments")
async def list_payments(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all payments for a period."""
    from app.domain.services.gst_payment import get_payment_summary
    try:
        summary = await get_payment_summary(period_id, db)
    except Exception as exc:
        logger.exception("Payment summary failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", "data": summary}


@router.post("/periods/{period_id}/validate-payment", summary="Validate payment vs liability")
async def validate_payment_endpoint(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Validate total payments against computed liability."""
    from app.domain.services.gst_payment import validate_payment as do_validate
    try:
        result = await do_validate(period_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Payment validation failed for period %s", period_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", "data": result.to_dict()}
