# app/domain/services/segment_detection.py
"""
Segment auto-detection for business clients.

Uses turnover, invoice volume, GSTIN count, and export status
to classify clients into small / medium / enterprise segments.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("segment_detection")

# Thresholds (in INR)
_ENTERPRISE_TURNOVER = Decimal("50_00_00_000")   # 50 Crore
_MEDIUM_TURNOVER = Decimal("5_00_00_000")         # 5 Crore
_MEDIUM_INVOICE_VOLUME = 100                       # monthly invoices
_ENTERPRISE_GSTIN_COUNT = 5
_MEDIUM_GSTIN_COUNT = 2

# Valid segment values
VALID_SEGMENTS = ("small", "medium", "enterprise")


def detect_segment(
    annual_turnover: float | Decimal | None = None,
    monthly_invoice_volume: int | None = None,
    gstin_count: int = 1,
    is_exporter: bool = False,
) -> str:
    """Auto-detect segment based on business metrics.

    Rules (checked top-down, first match wins):
    - enterprise: turnover >= 50Cr OR gstin_count >= 5 OR is_exporter
    - medium:     turnover >= 5Cr OR monthly_invoice_volume >= 100 OR gstin_count >= 2
    - small:      everything else
    """
    turnover = Decimal(str(annual_turnover)) if annual_turnover else Decimal("0")
    inv_vol = monthly_invoice_volume or 0

    # Enterprise checks
    if turnover >= _ENTERPRISE_TURNOVER:
        return "enterprise"
    if gstin_count >= _ENTERPRISE_GSTIN_COUNT:
        return "enterprise"
    if is_exporter:
        return "enterprise"

    # Medium checks
    if turnover >= _MEDIUM_TURNOVER:
        return "medium"
    if inv_vol >= _MEDIUM_INVOICE_VOLUME:
        return "medium"
    if gstin_count >= _MEDIUM_GSTIN_COUNT:
        return "medium"

    return "small"


async def auto_segment_client(client_id: int, db: AsyncSession) -> str:
    """Re-detect and update segment for a client.

    Skips if ``segment_override=True`` (CA manually set segment).
    Returns the (possibly updated) segment string.
    """
    from app.infrastructure.db.models import BusinessClient

    stmt = select(BusinessClient).where(BusinessClient.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    if not client:
        logger.warning("auto_segment_client: client_id=%d not found", client_id)
        return "small"

    # Respect manual override
    if client.segment_override:
        logger.debug(
            "auto_segment_client: client_id=%d has override, keeping '%s'",
            client_id, client.segment,
        )
        return client.segment

    new_segment = detect_segment(
        annual_turnover=client.annual_turnover,
        monthly_invoice_volume=client.monthly_invoice_volume,
        gstin_count=client.gstin_count,
        is_exporter=client.is_exporter,
    )

    if new_segment != client.segment:
        old_segment = client.segment
        client.segment = new_segment
        await db.flush()
        logger.info(
            "auto_segment_client: client_id=%d segment changed %s → %s",
            client_id, old_segment, new_segment,
        )

        # Invalidate feature cache
        from app.domain.services.feature_registry import invalidate_feature_cache
        await invalidate_feature_cache(client_id)

    return new_segment
