# app/domain/services/gst_payment.py
"""
Payment tracking service for GST return periods.

Supports recording challan payments, validating against computed liability,
and summarizing payment status.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import ReturnPeriod, PaymentRecord

logger = logging.getLogger("gst_payment")


@dataclass
class PaymentValidation:
    """Result of comparing payments vs computed liability."""
    net_payable_igst: float = 0
    net_payable_cgst: float = 0
    net_payable_sgst: float = 0
    net_payable_total: float = 0

    paid_igst: float = 0
    paid_cgst: float = 0
    paid_sgst: float = 0
    paid_cess: float = 0
    paid_total: float = 0

    shortfall_igst: float = 0
    shortfall_cgst: float = 0
    shortfall_sgst: float = 0
    shortfall_total: float = 0

    overpayment: float = 0
    is_fully_paid: bool = False
    payment_count: int = 0

    def to_dict(self) -> dict:
        return {
            "net_payable": {
                "igst": self.net_payable_igst,
                "cgst": self.net_payable_cgst,
                "sgst": self.net_payable_sgst,
                "total": self.net_payable_total,
            },
            "paid": {
                "igst": self.paid_igst,
                "cgst": self.paid_cgst,
                "sgst": self.paid_sgst,
                "cess": self.paid_cess,
                "total": self.paid_total,
            },
            "shortfall": {
                "igst": self.shortfall_igst,
                "cgst": self.shortfall_cgst,
                "sgst": self.shortfall_sgst,
                "total": self.shortfall_total,
            },
            "overpayment": self.overpayment,
            "is_fully_paid": self.is_fully_paid,
            "payment_count": self.payment_count,
        }


async def record_payment(
    period_id: UUID,
    challan_data: dict[str, Any],
    db: AsyncSession,
) -> PaymentRecord:
    """Record a new payment/challan entry for a period.

    ``challan_data`` keys: challan_number, challan_date, igst, cgst, sgst,
    cess, total, payment_mode, bank_reference, notes.
    """
    from app.infrastructure.db.repositories.payment_repository import PaymentRepository

    repo = PaymentRepository(db)
    payment = await repo.create(period_id, challan_data)
    logger.info(
        "Payment recorded for period %s: challan=%s total=₹%s",
        period_id, payment.challan_number, payment.total,
    )
    return payment


async def validate_payment(
    period_id: UUID,
    db: AsyncSession,
) -> PaymentValidation:
    """Compare total confirmed payments vs net liability for a period."""
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )
    from app.infrastructure.db.repositories.payment_repository import PaymentRepository

    rp_repo = ReturnPeriodRepository(db)
    pay_repo = PaymentRepository(db)

    rp = await rp_repo.get_by_id(period_id)
    if not rp:
        raise ValueError(f"Period {period_id} not found")

    totals = await pay_repo.get_total_paid(period_id)
    payments = await pay_repo.list_for_period(period_id)

    v = PaymentValidation()
    v.net_payable_igst = float(rp.net_payable_igst or 0)
    v.net_payable_cgst = float(rp.net_payable_cgst or 0)
    v.net_payable_sgst = float(rp.net_payable_sgst or 0)
    v.net_payable_total = v.net_payable_igst + v.net_payable_cgst + v.net_payable_sgst

    v.paid_igst = float(totals["igst"])
    v.paid_cgst = float(totals["cgst"])
    v.paid_sgst = float(totals["sgst"])
    v.paid_cess = float(totals["cess"])
    v.paid_total = float(totals["total"])

    v.shortfall_igst = max(0, v.net_payable_igst - v.paid_igst)
    v.shortfall_cgst = max(0, v.net_payable_cgst - v.paid_cgst)
    v.shortfall_sgst = max(0, v.net_payable_sgst - v.paid_sgst)
    v.shortfall_total = v.shortfall_igst + v.shortfall_cgst + v.shortfall_sgst

    v.overpayment = max(0, v.paid_total - v.net_payable_total)
    v.is_fully_paid = v.shortfall_total <= 0
    v.payment_count = len(payments)

    return v


async def get_payment_summary(
    period_id: UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    """High-level payment summary: total paid, pending, shortfall."""
    from app.infrastructure.db.repositories.payment_repository import PaymentRepository

    pay_repo = PaymentRepository(db)
    payments = await pay_repo.list_for_period(period_id)
    totals = await pay_repo.get_total_paid(period_id)

    confirmed = [p for p in payments if p.status == "confirmed"]
    pending = [p for p in payments if p.status == "pending"]

    return {
        "total_payments": len(payments),
        "confirmed_count": len(confirmed),
        "pending_count": len(pending),
        "total_confirmed": float(totals["total"]),
        "total_pending": float(sum(
            (p.total or Decimal("0")) for p in pending
        )),
        "payments": [
            {
                "id": str(p.id),
                "challan_number": p.challan_number,
                "challan_date": p.challan_date.isoformat() if p.challan_date else None,
                "total": float(p.total or 0),
                "status": p.status,
                "payment_mode": p.payment_mode,
            }
            for p in payments
        ],
    }
