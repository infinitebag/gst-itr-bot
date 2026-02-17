# app/infrastructure/db/repositories/annual_return_repository.py
"""Repository for AnnualReturn (GSTR-9) CRUD and status management."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import AnnualReturn


class AnnualReturnRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_or_get(
        self,
        user_id: uuid.UUID,
        gstin: str,
        fy: str,
    ) -> AnnualReturn:
        """Idempotent: find existing or create new AnnualReturn for (gstin, fy)."""
        stmt = select(AnnualReturn).where(
            and_(
                AnnualReturn.gstin == gstin,
                AnnualReturn.fy == fy,
            )
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        ar = AnnualReturn(
            id=uuid.uuid4(),
            user_id=user_id,
            gstin=gstin,
            fy=fy,
        )
        self.db.add(ar)
        await self.db.commit()
        await self.db.refresh(ar)
        return ar

    async def get_by_id(self, annual_id: uuid.UUID) -> AnnualReturn | None:
        stmt = select(AnnualReturn).where(AnnualReturn.id == annual_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_user(
        self,
        user_id: uuid.UUID,
        fy: str | None = None,
    ) -> list[AnnualReturn]:
        """List annual returns for a user, optionally filtered by FY."""
        stmt = select(AnnualReturn).where(AnnualReturn.user_id == user_id)
        if fy:
            stmt = stmt.where(AnnualReturn.fy == fy)
        stmt = stmt.order_by(AnnualReturn.fy.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_computation(
        self,
        annual_id: uuid.UUID,
        data: dict[str, Any],
    ) -> AnnualReturn | None:
        """Store aggregated computation values."""
        ar = await self.get_by_id(annual_id)
        if not ar:
            return None

        for field in (
            "total_outward_taxable",
            "total_inward_taxable",
            "total_itc_claimed",
            "total_itc_reversed",
            "total_tax_paid",
            "risk_score",
        ):
            if field in data:
                setattr(ar, field, data[field])

        if "monthly_vs_annual_diff" in data:
            ar.monthly_vs_annual_diff = json.dumps(data["monthly_vs_annual_diff"])
        if "books_vs_gst_diff" in data:
            ar.books_vs_gst_diff = json.dumps(data["books_vs_gst_diff"])

        ar.computed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(ar)
        return ar

    async def update_status(
        self,
        annual_id: uuid.UUID,
        new_status: str,
    ) -> AnnualReturn | None:
        """Update annual return status."""
        ar = await self.get_by_id(annual_id)
        if not ar:
            return None

        # Valid transitions for annual return
        _ANNUAL_TRANSITIONS = {
            "draft": ["aggregated"],
            "aggregated": ["ca_review", "draft"],
            "ca_review": ["approved", "aggregated"],
            "approved": ["filed", "ca_review"],
            "filed": ["closed"],
            "closed": [],
        }

        valid_next = _ANNUAL_TRANSITIONS.get(ar.status, [])
        if new_status not in valid_next:
            from app.domain.services.gst_workflow import InvalidPeriodTransitionError
            raise InvalidPeriodTransitionError(
                f"Cannot transition annual return from '{ar.status}' to '{new_status}'. "
                f"Valid: {valid_next}"
            )

        ar.status = new_status
        await self.db.commit()
        await self.db.refresh(ar)
        return ar
