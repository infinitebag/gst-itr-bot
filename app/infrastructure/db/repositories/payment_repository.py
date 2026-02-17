# app/infrastructure/db/repositories/payment_repository.py
"""Repository for PaymentRecord CRUD and payment aggregation."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import PaymentRecord


class PaymentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        period_id: uuid.UUID,
        data: dict[str, Any],
    ) -> PaymentRecord:
        """Record a new payment / challan entry for a period."""
        pr = PaymentRecord(
            id=uuid.uuid4(),
            period_id=period_id,
            challan_number=data.get("challan_number"),
            challan_date=data.get("challan_date"),
            igst=Decimal(str(data.get("igst", 0))),
            cgst=Decimal(str(data.get("cgst", 0))),
            sgst=Decimal(str(data.get("sgst", 0))),
            cess=Decimal(str(data.get("cess", 0))),
            total=Decimal(str(data.get("total", 0))),
            payment_mode=data.get("payment_mode"),
            bank_reference=data.get("bank_reference"),
            status=data.get("status", "pending"),
            notes=data.get("notes"),
        )
        self.db.add(pr)
        await self.db.commit()
        await self.db.refresh(pr)
        return pr

    async def get_by_id(self, payment_id: uuid.UUID) -> PaymentRecord | None:
        stmt = select(PaymentRecord).where(PaymentRecord.id == payment_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_period(
        self, period_id: uuid.UUID
    ) -> list[PaymentRecord]:
        """List all payments for a return period, most recent first."""
        stmt = (
            select(PaymentRecord)
            .where(PaymentRecord.period_id == period_id)
            .order_by(PaymentRecord.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_total_paid(
        self, period_id: uuid.UUID
    ) -> dict[str, Decimal]:
        """Sum confirmed payments for a period by tax head."""
        stmt = select(PaymentRecord).where(
            and_(
                PaymentRecord.period_id == period_id,
                PaymentRecord.status == "confirmed",
            )
        )
        result = await self.db.execute(stmt)
        payments = list(result.scalars().all())

        totals: dict[str, Decimal] = {
            "igst": Decimal("0"),
            "cgst": Decimal("0"),
            "sgst": Decimal("0"),
            "cess": Decimal("0"),
            "total": Decimal("0"),
        }
        for p in payments:
            totals["igst"] += p.igst or Decimal("0")
            totals["cgst"] += p.cgst or Decimal("0")
            totals["sgst"] += p.sgst or Decimal("0")
            totals["cess"] += p.cess or Decimal("0")
            totals["total"] += p.total or Decimal("0")

        return totals

    async def update_status(
        self,
        payment_id: uuid.UUID,
        status: str,
    ) -> PaymentRecord | None:
        """Update payment status (pending / confirmed / failed)."""
        pr = await self.get_by_id(payment_id)
        if not pr:
            return None
        pr.status = status
        await self.db.commit()
        await self.db.refresh(pr)
        return pr
