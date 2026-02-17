# app/infrastructure/db/repositories/return_period_repository.py
"""Repository for ReturnPeriod CRUD and status management."""

from __future__ import annotations

import json
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import ReturnPeriod


def _period_to_fy(period: str) -> str:
    """Convert 'YYYY-MM' to Indian financial year 'YYYY-YY'.

    FY runs April to March:
      - 2025-01 → 2024-25  (Jan 2025 falls in FY Apr 2024 – Mar 2025)
      - 2025-04 → 2025-26  (Apr 2025 starts FY 2025-26)
    """
    parts = period.split("-")
    year, month = int(parts[0]), int(parts[1])
    if month >= 4:  # Apr-Dec → FY starts this year
        fy_start = year
    else:  # Jan-Mar → FY started last year
        fy_start = year - 1
    fy_end = (fy_start + 1) % 100
    return f"{fy_start}-{fy_end:02d}"


def _compute_due_dates(period: str) -> tuple[date, date]:
    """Compute GSTR-1 and GSTR-3B due dates for a period.

    GSTR-1: 11th of the month following the period.
    GSTR-3B: 20th of the month following the period.
    """
    parts = period.split("-")
    year, month = int(parts[0]), int(parts[1])
    # Next month
    if month == 12:
        nm_year, nm_month = year + 1, 1
    else:
        nm_year, nm_month = year, month + 1
    return date(nm_year, nm_month, 11), date(nm_year, nm_month, 20)


def _period_date_range(period: str) -> tuple[date, date]:
    """Return (first_day, last_day) for a YYYY-MM period."""
    parts = period.split("-")
    year, month = int(parts[0]), int(parts[1])
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return start, end


class ReturnPeriodRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_or_get(
        self,
        user_id: uuid.UUID,
        gstin: str,
        period: str,
    ) -> ReturnPeriod:
        """Idempotent: find existing or create new ReturnPeriod for (gstin, period)."""
        stmt = select(ReturnPeriod).where(
            and_(
                ReturnPeriod.gstin == gstin,
                ReturnPeriod.period == period,
            )
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        fy = _period_to_fy(period)
        gstr1_due, gstr3b_due = _compute_due_dates(period)

        rp = ReturnPeriod(
            id=uuid.uuid4(),
            user_id=user_id,
            gstin=gstin,
            fy=fy,
            period=period,
            due_date_gstr1=gstr1_due,
            due_date_gstr3b=gstr3b_due,
        )
        self.db.add(rp)
        await self.db.commit()
        await self.db.refresh(rp)
        return rp

    async def get_by_id(self, period_id: uuid.UUID) -> ReturnPeriod | None:
        stmt = select(ReturnPeriod).where(ReturnPeriod.id == period_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        fy: str | None = None,
        limit: int = 12,
    ) -> list[ReturnPeriod]:
        """List return periods, most recent first, optionally filtered by FY."""
        stmt = select(ReturnPeriod).where(ReturnPeriod.user_id == user_id)
        if fy:
            stmt = stmt.where(ReturnPeriod.fy == fy)
        stmt = stmt.order_by(ReturnPeriod.period.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_computation(
        self,
        period_id: uuid.UUID,
        computation: dict[str, Any],
    ) -> ReturnPeriod | None:
        """Store computed tax values from the liability computation."""
        rp = await self.get_by_id(period_id)
        if not rp:
            return None

        for field in (
            "outward_count", "inward_count",
            "output_tax_igst", "output_tax_cgst", "output_tax_sgst",
            "itc_igst", "itc_cgst", "itc_sgst",
            "net_payable_igst", "net_payable_cgst", "net_payable_sgst",
            "rcm_igst", "rcm_cgst", "rcm_sgst",
        ):
            if field in computation:
                setattr(rp, field, computation[field])

        if "risk_flags" in computation:
            rp.risk_flags = json.dumps(computation["risk_flags"])

        rp.computed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(rp)
        return rp

    async def update_status(
        self,
        period_id: uuid.UUID,
        new_status: str,
    ) -> ReturnPeriod | None:
        """Update status with transition validation."""
        from app.domain.services.gst_workflow import validate_period_transition

        rp = await self.get_by_id(period_id)
        if not rp:
            return None

        validate_period_transition(rp.status, new_status)
        rp.status = new_status
        await self.db.commit()
        await self.db.refresh(rp)
        return rp

    async def link_filing(
        self,
        period_id: uuid.UUID,
        form_type: str,
        filing_id: uuid.UUID,
    ) -> ReturnPeriod | None:
        """Link a GSTR-1 or GSTR-3B filing record to this period."""
        rp = await self.get_by_id(period_id)
        if not rp:
            return None

        if "GSTR-1" in form_type:
            rp.gstr1_filing_id = filing_id
        elif "GSTR-3B" in form_type:
            rp.gstr3b_filing_id = filing_id

        await self.db.commit()
        await self.db.refresh(rp)
        return rp

    async def list_for_fy(
        self,
        user_id: uuid.UUID,
        fy: str,
    ) -> list[ReturnPeriod]:
        """List all periods for a user in a financial year (for annual aggregation)."""
        stmt = (
            select(ReturnPeriod)
            .where(
                and_(
                    ReturnPeriod.user_id == user_id,
                    ReturnPeriod.fy == fy,
                )
            )
            .order_by(ReturnPeriod.period.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
