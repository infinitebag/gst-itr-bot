# app/domain/services/refund_service.py
"""
GST Refund claim management service.

Handles creation, tracking, and status updates for GST refund claims.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("refund_service")

REFUND_TYPES = {
    "1": "excess_balance",
    "2": "export",
    "3": "inverted_duty",
}

REFUND_TYPE_LABELS = {
    "excess_balance": "Excess Cash Balance",
    "export": "Export Refund",
    "inverted_duty": "Inverted Duty Structure",
}


async def create_refund_claim(
    gstin: str,
    user_id: int,
    claim_type: str,
    amount: float,
    period: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Create a new refund claim draft.

    Returns
    -------
    dict
        ``{"success": True, "claim_id": int, ...}`` or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.db.models import RefundClaim

    claim = RefundClaim(
        gstin=gstin,
        user_id=user_id,
        claim_type=claim_type,
        amount=amount,
        period=period,
        status="draft",
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)

    return {
        "success": True,
        "claim_id": claim.id,
        "claim_type": claim_type,
        "amount": amount,
        "status": "draft",
    }


async def get_refund_status(claim_id: int, db: AsyncSession) -> dict[str, Any] | None:
    """Get the current status of a refund claim."""
    from app.infrastructure.db.models import RefundClaim

    stmt = select(RefundClaim).where(RefundClaim.id == claim_id)
    result = await db.execute(stmt)
    claim = result.scalar_one_or_none()
    if not claim:
        return None

    return {
        "claim_id": claim.id,
        "gstin": claim.gstin,
        "claim_type": claim.claim_type,
        "amount": float(claim.amount) if claim.amount else 0,
        "period": claim.period,
        "status": claim.status,
        "arn": claim.arn,
        "created_at": str(claim.created_at) if claim.created_at else None,
    }


async def list_refund_claims(
    gstin: str,
    db: AsyncSession,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List recent refund claims for a GSTIN."""
    from app.infrastructure.db.models import RefundClaim

    stmt = (
        select(RefundClaim)
        .where(RefundClaim.gstin == gstin)
        .order_by(RefundClaim.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    claims = result.scalars().all()

    return [
        {
            "claim_id": c.id,
            "claim_type": c.claim_type,
            "amount": float(c.amount) if c.amount else 0,
            "period": c.period,
            "status": c.status,
            "arn": c.arn,
        }
        for c in claims
    ]
