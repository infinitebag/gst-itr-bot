# app/domain/services/gst_composition.py
"""
Composition taxpayer workflow — CMP-08 quarterly filing.

Composition taxpayers:
  - Pay a fixed % of turnover (1% traders, 5% restaurants, etc.)
  - Cannot claim ITC
  - File CMP-08 quarterly + GSTR-4 annually
  - No GSTR-2B reconciliation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    BusinessClient,
    Invoice,
    ReturnPeriod,
)

logger = logging.getLogger("gst_composition")

# Default composition rate: 1% for traders, 5% for restaurants, 6% for manufacturers
_DEFAULT_COMPOSITION_RATE = Decimal("1.0")


@dataclass
class CompositionComputation:
    """Result of quarterly composition liability computation."""
    turnover: float = 0
    composition_rate: float = 0
    tax_amount: float = 0
    cgst: float = 0
    sgst: float = 0
    outward_count: int = 0
    period: str = ""
    quarter: str = ""  # e.g. "Q1 (Apr-Jun)"

    def to_dict(self) -> dict:
        return {
            "turnover": self.turnover,
            "composition_rate": self.composition_rate,
            "tax_amount": self.tax_amount,
            "cgst": self.cgst,
            "sgst": self.sgst,
            "outward_count": self.outward_count,
            "period": self.period,
            "quarter": self.quarter,
        }


async def compute_composition_liability(
    period_id: UUID,
    db: AsyncSession,
) -> CompositionComputation:
    """Compute composition tax liability for a period.

    Tax = Turnover × composition_rate
    Split equally into CGST + SGST (composition is always intra-state).
    No ITC, no IGST.
    """
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp:
        raise ValueError(f"Period {period_id} not found")

    # Get composition rate from BusinessClient
    rate = _DEFAULT_COMPOSITION_RATE
    bc_stmt = select(BusinessClient).where(BusinessClient.gstin == rp.gstin)
    bc_result = await db.execute(bc_stmt)
    bc = bc_result.scalar_one_or_none()
    if bc and bc.composition_rate:
        rate = Decimal(str(bc.composition_rate))

    # Aggregate outward taxable value for this period
    inv_stmt = select(Invoice).where(
        and_(
            Invoice.user_id == rp.user_id,
            Invoice.direction == "outward",
            Invoice.invoice_date.isnot(None),
        )
    )
    inv_result = await db.execute(inv_stmt)
    invoices = list(inv_result.scalars().all())

    # Filter invoices belonging to this period (YYYY-MM)
    period_invoices = [
        inv for inv in invoices
        if inv.invoice_date and inv.invoice_date.strftime("%Y-%m") == rp.period
    ]

    turnover = sum(
        (inv.taxable_value or Decimal("0")) for inv in period_invoices
    )
    tax = turnover * rate / Decimal("100")
    half_tax = tax / Decimal("2")

    comp = CompositionComputation(
        turnover=float(turnover),
        composition_rate=float(rate),
        tax_amount=float(tax),
        cgst=float(half_tax),
        sgst=float(tax - half_tax),  # handle rounding
        outward_count=len(period_invoices),
        period=rp.period,
        quarter=_period_to_quarter(rp.period),
    )

    # Store in ReturnPeriod (no ITC for composition)
    await repo.update_computation(period_id, {
        "outward_count": comp.outward_count,
        "output_tax_cgst": comp.cgst,
        "output_tax_sgst": comp.sgst,
        "output_tax_igst": 0,
        "itc_igst": 0,
        "itc_cgst": 0,
        "itc_sgst": 0,
        "net_payable_cgst": comp.cgst,
        "net_payable_sgst": comp.sgst,
        "net_payable_igst": 0,
        "rcm_igst": 0,
        "rcm_cgst": 0,
        "rcm_sgst": 0,
        "risk_flags": [],
    })

    logger.info(
        "Composition liability computed for period %s: turnover=₹%.2f, tax=₹%.2f @ %.1f%%",
        period_id, comp.turnover, comp.tax_amount, comp.composition_rate,
    )
    return comp


async def prepare_cmp08(
    period_id: UUID,
    db: AsyncSession,
) -> dict:
    """Build CMP-08 form values from computed data.

    CMP-08 is the quarterly statement for composition taxpayers.
    """
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    repo = ReturnPeriodRepository(db)
    rp = await repo.get_by_id(period_id)
    if not rp:
        raise ValueError(f"Period {period_id} not found")

    return {
        "form": "CMP-08",
        "gstin": rp.gstin,
        "period": rp.period,
        "quarter": _period_to_quarter(rp.period),
        "fy": rp.fy,
        "outward_supplies": {
            "taxable_value": float(
                (rp.output_tax_cgst or Decimal("0"))
                + (rp.output_tax_sgst or Decimal("0"))
            ),
            "cgst": float(rp.output_tax_cgst or 0),
            "sgst": float(rp.output_tax_sgst or 0),
            "total_tax": float(
                (rp.output_tax_cgst or Decimal("0"))
                + (rp.output_tax_sgst or Decimal("0"))
            ),
        },
        "interest": float(rp.interest or 0),
        "late_fee": float(rp.late_fee or 0),
        "total_payable": float(
            (rp.net_payable_cgst or Decimal("0"))
            + (rp.net_payable_sgst or Decimal("0"))
            + (rp.interest or Decimal("0"))
            + (rp.late_fee or Decimal("0"))
        ),
    }


async def prepare_gstr4_annual(
    user_id: UUID,
    gstin: str,
    fy: str,
    db: AsyncSession,
) -> dict:
    """Aggregate 4 quarterly CMP-08 periods into GSTR-4 annual return values."""
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    repo = ReturnPeriodRepository(db)
    periods = await repo.list_for_fy(user_id, fy)

    total_turnover = Decimal("0")
    total_cgst = Decimal("0")
    total_sgst = Decimal("0")
    total_outward = 0
    quarterly_data = []

    for p in periods:
        turnover = (p.output_tax_cgst or Decimal("0")) + (p.output_tax_sgst or Decimal("0"))
        total_turnover += turnover
        total_cgst += p.net_payable_cgst or Decimal("0")
        total_sgst += p.net_payable_sgst or Decimal("0")
        total_outward += p.outward_count or 0
        quarterly_data.append({
            "period": p.period,
            "quarter": _period_to_quarter(p.period),
            "turnover": float(turnover),
            "cgst": float(p.net_payable_cgst or 0),
            "sgst": float(p.net_payable_sgst or 0),
            "status": p.status,
        })

    return {
        "form": "GSTR-4",
        "gstin": gstin,
        "fy": fy,
        "total_turnover": float(total_turnover),
        "total_cgst": float(total_cgst),
        "total_sgst": float(total_sgst),
        "total_tax": float(total_cgst + total_sgst),
        "total_outward_count": total_outward,
        "quarterly_breakdown": quarterly_data,
    }


def _period_to_quarter(period: str) -> str:
    """Convert YYYY-MM to quarter label."""
    month = int(period.split("-")[1])
    if month in (4, 5, 6):
        return "Q1 (Apr-Jun)"
    elif month in (7, 8, 9):
        return "Q2 (Jul-Sep)"
    elif month in (10, 11, 12):
        return "Q3 (Oct-Dec)"
    else:
        return "Q4 (Jan-Mar)"
