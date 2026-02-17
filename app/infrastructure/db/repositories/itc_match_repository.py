# app/infrastructure/db/repositories/itc_match_repository.py
"""Repository for ITCMatch CRUD — GSTR-2B entries and reconciliation results."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import ITCMatch


class ITCMatchRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def bulk_create(
        self,
        period_id: uuid.UUID,
        matches: list[dict],
    ) -> int:
        """Batch insert ITCMatch records from 2B import. Returns count inserted."""
        if not matches:
            return 0

        objects = []
        for m in matches:
            obj = ITCMatch(
                id=uuid.uuid4(),
                period_id=period_id,
                purchase_invoice_id=m.get("purchase_invoice_id"),
                gstr2b_supplier_gstin=m["gstr2b_supplier_gstin"],
                gstr2b_invoice_number=m["gstr2b_invoice_number"],
                gstr2b_invoice_date=m.get("gstr2b_invoice_date"),
                gstr2b_taxable_value=m["gstr2b_taxable_value"],
                gstr2b_igst=m.get("gstr2b_igst", Decimal("0")),
                gstr2b_cgst=m.get("gstr2b_cgst", Decimal("0")),
                gstr2b_sgst=m.get("gstr2b_sgst", Decimal("0")),
                match_status=m.get("match_status", "unmatched"),
                mismatch_details=(
                    json.dumps(m["mismatch_details"])
                    if m.get("mismatch_details")
                    else None
                ),
            )
            objects.append(obj)

        self.db.add_all(objects)
        await self.db.commit()
        return len(objects)

    async def list_for_period(
        self,
        period_id: uuid.UUID,
        status: str | None = None,
    ) -> list[ITCMatch]:
        """List ITCMatch records for a period, optionally filtered by match_status."""
        stmt = select(ITCMatch).where(ITCMatch.period_id == period_id)
        if status:
            stmt = stmt.where(ITCMatch.match_status == status)
        stmt = stmt.order_by(ITCMatch.gstr2b_supplier_gstin, ITCMatch.gstr2b_invoice_number)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_summary(self, period_id: uuid.UUID) -> dict:
        """Return aggregated counts and amounts grouped by match_status.

        Returns
        -------
        dict like:
            {
                "matched": {"count": 10, "taxable": 50000, "igst": ..., "cgst": ..., "sgst": ...},
                "value_mismatch": {...},
                "missing_in_books": {...},
                "unmatched": {...},
                "total": {"count": 25, "taxable": ...}
            }
        """
        stmt = (
            select(
                ITCMatch.match_status,
                func.count(ITCMatch.id).label("count"),
                func.sum(ITCMatch.gstr2b_taxable_value).label("taxable"),
                func.sum(ITCMatch.gstr2b_igst).label("igst"),
                func.sum(ITCMatch.gstr2b_cgst).label("cgst"),
                func.sum(ITCMatch.gstr2b_sgst).label("sgst"),
            )
            .where(ITCMatch.period_id == period_id)
            .group_by(ITCMatch.match_status)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        summary: dict = {}
        total_count = 0
        total_taxable = Decimal("0")

        for row in rows:
            status_key = row.match_status
            count = row.count or 0
            taxable = row.taxable or Decimal("0")
            summary[status_key] = {
                "count": count,
                "taxable": float(taxable),
                "igst": float(row.igst or 0),
                "cgst": float(row.cgst or 0),
                "sgst": float(row.sgst or 0),
            }
            total_count += count
            total_taxable += taxable

        summary["total"] = {
            "count": total_count,
            "taxable": float(total_taxable),
        }

        return summary

    async def clear_for_period(self, period_id: uuid.UUID) -> int:
        """Delete all ITCMatch records for a period (before re-import). Returns deleted count."""
        stmt = delete(ITCMatch).where(ITCMatch.period_id == period_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount  # type: ignore[return-value]

    async def update_match(
        self,
        match_id: uuid.UUID,
        purchase_invoice_id: uuid.UUID | None,
        match_status: str,
        mismatch_details: dict | None = None,
    ) -> ITCMatch | None:
        """Update a single match record after reconciliation."""
        stmt = select(ITCMatch).where(ITCMatch.id == match_id)
        result = await self.db.execute(stmt)
        match = result.scalar_one_or_none()
        if not match:
            return None

        match.purchase_invoice_id = purchase_invoice_id
        match.match_status = match_status
        if mismatch_details is not None:
            match.mismatch_details = json.dumps(mismatch_details)

        await self.db.commit()
        await self.db.refresh(match)
        return match
