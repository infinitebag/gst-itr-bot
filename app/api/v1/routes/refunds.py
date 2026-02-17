# app/api/v1/routes/refunds.py
"""GST Refund tracking API (Phase 9A)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok, error, paginated
from app.core.db import get_db
from app.infrastructure.db.models import User

logger = logging.getLogger("api.v1.refunds")

router = APIRouter(prefix="/refunds", tags=["Refund Tracking"])


class CreateRefundRequest(BaseModel):
    gstin: str = Field(..., min_length=15, max_length=15)
    claim_type: str = Field(..., description="excess_balance | export | inverted_duty")
    amount: float = Field(..., gt=0)
    period: str = Field(default="", description="YYYY-MM format")


@router.get("/")
async def list_refunds(
    gstin: str = Query(..., min_length=15, max_length=15),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all refund claims for a GSTIN."""
    from app.domain.services.refund_service import list_refund_claims
    claims = await list_refund_claims(gstin, db)
    return ok(data=claims, message=f"Found {len(claims)} claim(s)")


@router.post("/")
async def create_refund(
    body: CreateRefundRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new refund claim."""
    from app.domain.services.refund_service import create_refund_claim
    from app.domain.services.gst_service import get_current_gst_period
    period = body.period or get_current_gst_period()
    result = await create_refund_claim(body.gstin, user.id, body.claim_type, body.amount, period, db)
    return ok(data=result, message="Refund claim created")


@router.get("/{claim_id}")
async def get_refund(
    claim_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific refund claim."""
    from app.domain.services.refund_service import get_refund_status
    claim = await get_refund_status(claim_id, db)
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return ok(data=claim)
