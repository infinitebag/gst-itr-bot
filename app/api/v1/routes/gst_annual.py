# app/api/v1/routes/gst_annual.py
"""V1 API endpoints for GST annual returns (GSTR-9)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.infrastructure.db.models import User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok, error
from app.api.v1.schemas.annual import (
    AnnualCreateRequest,
    AnnualReturnResponse,
    AnnualStatusTransitionRequest,
)

logger = logging.getLogger("api.v1.gst_annual")

router = APIRouter(prefix="/gst/annual", tags=["GST Annual"])


@router.post("", summary="Create or get annual return")
async def create_annual(
    body: AnnualCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or retrieve an annual return for the authenticated user."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository

    repo = AnnualReturnRepository(db)
    ar = await repo.create_or_get(user.id, body.gstin, body.fy)
    return ok(data=_to_response(ar))


@router.get("", summary="List annual returns")
async def list_annual(
    fy: str | None = Query(None, description="Financial year filter"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List annual returns for the authenticated user."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository

    repo = AnnualReturnRepository(db)
    items = await repo.get_for_user(user.id, fy=fy)
    return ok(data=[_to_response(ar) for ar in items])


@router.get("/{annual_id}", summary="Get annual return detail")
async def get_annual(
    annual_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed annual return information."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository

    repo = AnnualReturnRepository(db)
    ar = await repo.get_by_id(annual_id)
    if not ar or ar.user_id != user.id:
        raise HTTPException(status_code=404, detail="Annual return not found")
    return ok(data=_to_response(ar))


@router.post("/{annual_id}/aggregate", summary="Aggregate 12 months")
async def aggregate_annual(
    annual_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate 12 monthly periods into annual return totals."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository
    from app.domain.services.gst_annual import aggregate_annual as do_aggregate

    repo = AnnualReturnRepository(db)
    ar = await repo.get_by_id(annual_id)
    if not ar or ar.user_id != user.id:
        raise HTTPException(status_code=404, detail="Annual return not found")

    try:
        result = await do_aggregate(user.id, ar.gstin, ar.fy, db)
    except Exception as exc:
        logger.exception("Annual aggregation failed for %s", annual_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(data=result.to_dict())


@router.post("/{annual_id}/transition", summary="Transition status")
async def transition_annual(
    annual_id: UUID,
    body: AnnualStatusTransitionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition annual return to a new status."""
    from app.infrastructure.db.repositories.annual_return_repository import AnnualReturnRepository
    from app.domain.services.gst_workflow import InvalidPeriodTransitionError

    repo = AnnualReturnRepository(db)
    ar = await repo.get_by_id(annual_id)
    if not ar or ar.user_id != user.id:
        raise HTTPException(status_code=404, detail="Annual return not found")

    try:
        updated = await repo.update_status(annual_id, body.new_status)
    except InvalidPeriodTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ok(data=_to_response(updated))


def _to_response(ar) -> dict:
    return AnnualReturnResponse(
        id=str(ar.id),
        user_id=str(ar.user_id),
        gstin=ar.gstin,
        fy=ar.fy,
        status=ar.status,
        total_outward_taxable=float(ar.total_outward_taxable or 0),
        total_inward_taxable=float(ar.total_inward_taxable or 0),
        total_itc_claimed=float(ar.total_itc_claimed or 0),
        total_itc_reversed=float(ar.total_itc_reversed or 0),
        total_tax_paid=float(ar.total_tax_paid or 0),
        risk_score=ar.risk_score,
        computed_at=ar.computed_at.isoformat() if ar.computed_at else None,
    ).model_dump()
