# app/api/routes/gst_annual.py
"""
REST API routes for GST annual return (GSTR-9) management.

Uses query-param auth (legacy pattern).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db

logger = logging.getLogger("gst_annual")
router = APIRouter()


# ============================================================
# Pydantic models
# ============================================================

class AnnualCreateRequest(BaseModel):
    user_id: str = Field(description="User UUID")
    gstin: str = Field(description="15-char GSTIN")
    fy: str = Field(description="Financial year e.g. 2024-25")


class AnnualStatusRequest(BaseModel):
    new_status: str = Field(description="Target status")


# ============================================================
# Endpoints
# ============================================================

@router.post("/annual", summary="Create or get annual return")
async def create_annual(
    body: AnnualCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create or retrieve an existing annual return for (gstin, fy)."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository

    repo = AnnualReturnRepository(db)
    ar = await repo.create_or_get(UUID(body.user_id), body.gstin, body.fy)
    return {"status": "ok", "data": _annual_to_response(ar)}


@router.get("/annual", summary="Get annual return")
async def get_annual(
    user_id: str = Query(..., description="User UUID"),
    fy: str | None = Query(None, description="Financial year filter"),
    db: AsyncSession = Depends(get_db),
):
    """Get annual returns for a user."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository

    repo = AnnualReturnRepository(db)
    items = await repo.get_for_user(UUID(user_id), fy=fy)
    return {
        "status": "ok",
        "data": [_annual_to_response(ar) for ar in items],
    }


@router.post("/annual/{annual_id}/aggregate", summary="Aggregate 12 months")
async def aggregate_annual(
    annual_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Aggregate 12 monthly periods into annual return."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository
    from app.domain.services.gst_annual import aggregate_annual as do_aggregate

    repo = AnnualReturnRepository(db)
    ar = await repo.get_by_id(annual_id)
    if not ar:
        raise HTTPException(status_code=404, detail="Annual return not found")

    try:
        result = await do_aggregate(ar.user_id, ar.gstin, ar.fy, db)
    except Exception as exc:
        logger.exception("Annual aggregation failed for %s", annual_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", "data": result.to_dict()}


@router.post("/annual/{annual_id}/transition", summary="Transition status")
async def transition_annual(
    annual_id: UUID,
    body: AnnualStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    """Transition annual return status."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository
    from app.domain.services.gst_workflow import InvalidPeriodTransitionError

    repo = AnnualReturnRepository(db)
    try:
        ar = await repo.update_status(annual_id, body.new_status)
    except InvalidPeriodTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not ar:
        raise HTTPException(status_code=404, detail="Annual return not found")

    return {"status": "ok", "data": _annual_to_response(ar)}


# ============================================================
# Helpers
# ============================================================

def _annual_to_response(ar) -> dict:
    return {
        "id": str(ar.id),
        "user_id": str(ar.user_id),
        "gstin": ar.gstin,
        "fy": ar.fy,
        "status": ar.status,
        "total_outward_taxable": float(ar.total_outward_taxable or 0),
        "total_inward_taxable": float(ar.total_inward_taxable or 0),
        "total_itc_claimed": float(ar.total_itc_claimed or 0),
        "total_itc_reversed": float(ar.total_itc_reversed or 0),
        "total_tax_paid": float(ar.total_tax_paid or 0),
        "risk_score": ar.risk_score,
        "computed_at": ar.computed_at.isoformat() if ar.computed_at else None,
    }
