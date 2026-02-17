# app/domain/services/gst_qrmp.py
"""
QRMP (Quarterly Return Monthly Payment) workflow.

QRMP taxpayers (turnover ≤ ₹5 Cr):
  - File GSTR-1 and GSTR-3B quarterly (months 3, 6, 9, 12 of FY)
  - Pay tax monthly via PMT-06 for non-quarter months
  - Optionally furnish IFF (Invoice Furnishing Facility) for B2B invoices monthly
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Invoice, ReturnPeriod

logger = logging.getLogger("gst_qrmp")

# Quarter-end months in Indian FY (April start)
_QUARTER_END_MONTHS = {6, 9, 12, 3}


@dataclass
class QRMPMonthlyPayment:
    """Monthly payment options under QRMP."""
    period: str
    is_quarter_end: bool = False

    # Method 1: 35% of last quarter's net liability
    method1_amount: float = 0
    method1_label: str = "35% of last quarter"

    # Method 2: Actual liability for the month
    method2_amount: float = 0
    method2_label: str = "Actual monthly liability"

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "is_quarter_end": self.is_quarter_end,
            "method1": {
                "amount": self.method1_amount,
                "label": self.method1_label,
            },
            "method2": {
                "amount": self.method2_amount,
                "label": self.method2_label,
            },
        }


@dataclass
class QuarterlyLiability:
    """Aggregated quarterly liability for QRMP filing."""
    quarter_periods: list[str] = field(default_factory=list)
    quarter_label: str = ""

    # Aggregated from 3 months
    output_igst: float = 0
    output_cgst: float = 0
    output_sgst: float = 0
    itc_igst: float = 0
    itc_cgst: float = 0
    itc_sgst: float = 0
    net_igst: float = 0
    net_cgst: float = 0
    net_sgst: float = 0
    total_net: float = 0

    # Monthly payments already made
    monthly_payments_total: float = 0
    remaining_payable: float = 0

    outward_count: int = 0
    inward_count: int = 0

    def to_dict(self) -> dict:
        return {
            "quarter_periods": self.quarter_periods,
            "quarter_label": self.quarter_label,
            "output": {
                "igst": self.output_igst,
                "cgst": self.output_cgst,
                "sgst": self.output_sgst,
            },
            "itc": {
                "igst": self.itc_igst,
                "cgst": self.itc_cgst,
                "sgst": self.itc_sgst,
            },
            "net": {
                "igst": self.net_igst,
                "cgst": self.net_cgst,
                "sgst": self.net_sgst,
                "total": self.total_net,
            },
            "monthly_payments_total": self.monthly_payments_total,
            "remaining_payable": self.remaining_payable,
            "outward_count": self.outward_count,
            "inward_count": self.inward_count,
        }


def is_quarter_end(period: str) -> bool:
    """Check if a period (YYYY-MM) is a quarter-end month in Indian FY."""
    month = int(period.split("-")[1])
    return month in _QUARTER_END_MONTHS


def get_quarter_periods(period: str) -> list[str]:
    """Given a quarter-end period, return all 3 months of that quarter.

    E.g. "2025-06" → ["2025-04", "2025-05", "2025-06"]
    """
    year = int(period.split("-")[0])
    month = int(period.split("-")[1])

    if month == 6:
        months = [(year, 4), (year, 5), (year, 6)]
    elif month == 9:
        months = [(year, 7), (year, 8), (year, 9)]
    elif month == 12:
        months = [(year, 10), (year, 11), (year, 12)]
    elif month == 3:
        months = [(year, 1), (year, 2), (year, 3)]
    else:
        # Not a quarter-end; return just this month
        return [period]

    return [f"{y}-{m:02d}" for y, m in months]


async def compute_monthly_payment(
    period_id: UUID,
    db: AsyncSession,
) -> QRMPMonthlyPayment:
    """Compute monthly payment options under QRMP for non-quarter months.

    Method 1: 35% of last quarter's net liability
    Method 2: Actual liability for the month
    """
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp:
        raise ValueError(f"Period {period_id} not found")

    result = QRMPMonthlyPayment(period=rp.period)
    result.is_quarter_end = is_quarter_end(rp.period)

    if result.is_quarter_end:
        # Quarter-end months: full filing, not monthly payment
        result.method1_label = "Full quarterly filing required"
        result.method2_label = "Full quarterly filing required"
        return result

    # Method 2: Actual liability for this month (from computed values)
    net = (
        float(rp.net_payable_igst or 0)
        + float(rp.net_payable_cgst or 0)
        + float(rp.net_payable_sgst or 0)
    )
    result.method2_amount = max(0, net)

    # Method 1: 35% of last quarter's net liability
    # Find the most recent quarter-end period for this GSTIN
    last_quarter = await _get_last_quarter_liability(rp.user_id, rp.gstin, rp.period, db)
    result.method1_amount = round(last_quarter * 0.35, 2)

    return result


async def compute_quarterly_liability(
    user_id: UUID,
    gstin: str,
    quarter_end_period: str,
    db: AsyncSession,
) -> QuarterlyLiability:
    """Aggregate 3 months into quarterly totals for QRMP filing.

    Adjusts for monthly payments already made in months 1 & 2.
    """
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )
    from app.infrastructure.db.repositories.payment_repository import PaymentRepository

    rp_repo = ReturnPeriodRepository(db)
    pay_repo = PaymentRepository(db)

    periods = get_quarter_periods(quarter_end_period)
    ql = QuarterlyLiability(
        quarter_periods=periods,
        quarter_label=_quarter_label(quarter_end_period),
    )

    monthly_paid = Decimal("0")

    for period_str in periods:
        # Find ReturnPeriod for this month
        stmt = select(ReturnPeriod).where(
            and_(
                ReturnPeriod.user_id == user_id,
                ReturnPeriod.gstin == gstin,
                ReturnPeriod.period == period_str,
            )
        )
        result = await db.execute(stmt)
        rp = result.scalar_one_or_none()
        if not rp:
            continue

        ql.output_igst += float(rp.output_tax_igst or 0)
        ql.output_cgst += float(rp.output_tax_cgst or 0)
        ql.output_sgst += float(rp.output_tax_sgst or 0)
        ql.itc_igst += float(rp.itc_igst or 0)
        ql.itc_cgst += float(rp.itc_cgst or 0)
        ql.itc_sgst += float(rp.itc_sgst or 0)
        ql.outward_count += rp.outward_count or 0
        ql.inward_count += rp.inward_count or 0

        # Sum payments for non-quarter-end months
        if period_str != quarter_end_period:
            totals = await pay_repo.get_total_paid(rp.id)
            monthly_paid += totals["total"]

    ql.net_igst = ql.output_igst - ql.itc_igst
    ql.net_cgst = ql.output_cgst - ql.itc_cgst
    ql.net_sgst = ql.output_sgst - ql.itc_sgst
    ql.total_net = ql.net_igst + ql.net_cgst + ql.net_sgst
    ql.monthly_payments_total = float(monthly_paid)
    ql.remaining_payable = max(0, ql.total_net - ql.monthly_payments_total)

    logger.info(
        "QRMP quarterly liability for %s %s: net=₹%.2f, paid=₹%.2f, remaining=₹%.2f",
        gstin, ql.quarter_label, ql.total_net, ql.monthly_payments_total, ql.remaining_payable,
    )
    return ql


async def prepare_iff(
    period_id: UUID,
    db: AsyncSession,
) -> dict:
    """Prepare Invoice Furnishing Facility (IFF) data — monthly B2B invoice summary.

    IFF is optional for QRMP taxpayers in non-quarter months.
    Only B2B invoices (with recipient GSTIN) are included.
    """
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp:
        raise ValueError(f"Period {period_id} not found")

    # Get B2B outward invoices for this period
    inv_stmt = select(Invoice).where(
        and_(
            Invoice.user_id == rp.user_id,
            Invoice.direction == "outward",
            Invoice.recipient_gstin.isnot(None),
        )
    )
    inv_result = await db.execute(inv_stmt)
    invoices = list(inv_result.scalars().all())

    # Filter to this period
    period_b2b = [
        inv for inv in invoices
        if inv.invoice_date and inv.invoice_date.strftime("%Y-%m") == rp.period
    ]

    entries = []
    for inv in period_b2b:
        entries.append({
            "recipient_gstin": inv.recipient_gstin,
            "invoice_number": inv.invoice_number,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "taxable_value": float(inv.taxable_value or 0),
            "igst": float(inv.igst_amount or 0),
            "cgst": float(inv.cgst_amount or 0),
            "sgst": float(inv.sgst_amount or 0),
            "total": float(inv.total_amount or 0),
        })

    return {
        "form": "IFF",
        "gstin": rp.gstin,
        "period": rp.period,
        "is_quarter_end": is_quarter_end(rp.period),
        "b2b_invoice_count": len(entries),
        "total_taxable": sum(e["taxable_value"] for e in entries),
        "entries": entries,
    }


async def _get_last_quarter_liability(
    user_id: UUID,
    gstin: str,
    current_period: str,
    db: AsyncSession,
) -> float:
    """Get total net liability from the most recent completed quarter."""
    year = int(current_period.split("-")[0])
    month = int(current_period.split("-")[1])

    # Determine the last quarter-end before current period
    if month in (4, 5):
        qe_year, qe_month = year, 3
    elif month in (7, 8):
        qe_year, qe_month = year, 6
    elif month in (10, 11):
        qe_year, qe_month = year, 9
    elif month in (1, 2):
        qe_year, qe_month = year - 1, 12
    else:
        # Current is quarter-end; use the one before
        if month == 6:
            qe_year, qe_month = year, 3
        elif month == 9:
            qe_year, qe_month = year, 6
        elif month == 12:
            qe_year, qe_month = year, 9
        elif month == 3:
            qe_year, qe_month = year - 1, 12
        else:
            return 0.0

    qe_period = f"{qe_year}-{qe_month:02d}"
    quarter_months = get_quarter_periods(qe_period)

    total = Decimal("0")
    for pm in quarter_months:
        stmt = select(ReturnPeriod).where(
            and_(
                ReturnPeriod.user_id == user_id,
                ReturnPeriod.gstin == gstin,
                ReturnPeriod.period == pm,
            )
        )
        result = await db.execute(stmt)
        rp = result.scalar_one_or_none()
        if rp:
            total += (rp.net_payable_igst or Decimal("0"))
            total += (rp.net_payable_cgst or Decimal("0"))
            total += (rp.net_payable_sgst or Decimal("0"))

    return float(total)


def _quarter_label(period: str) -> str:
    """Return quarter label for a period."""
    month = int(period.split("-")[1])
    if month in (4, 5, 6):
        return "Q1 (Apr-Jun)"
    elif month in (7, 8, 9):
        return "Q2 (Jul-Sep)"
    elif month in (10, 11, 12):
        return "Q3 (Oct-Dec)"
    else:
        return "Q4 (Jan-Mar)"
