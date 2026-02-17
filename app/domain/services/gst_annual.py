# app/domain/services/gst_annual.py
"""
Annual return (GSTR-9) aggregation across 12 monthly periods.

Computes:
  - Total outward/inward taxable values
  - ITC claimed vs available vs reversed
  - Per-month comparison (monthly_vs_annual_diff)
  - Books-vs-GST differences
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Invoice, ReturnPeriod

logger = logging.getLogger("gst_annual")


@dataclass
class AnnualReturnData:
    """Aggregated annual return computation."""
    gstin: str = ""
    fy: str = ""

    total_outward_taxable: float = 0
    total_inward_taxable: float = 0
    total_itc_claimed: float = 0
    total_itc_reversed: float = 0
    total_tax_paid: float = 0

    # Per-month breakdown
    monthly_breakdown: list[dict] = field(default_factory=list)

    # Discrepancies
    monthly_vs_annual_diff: list[dict] = field(default_factory=list)
    books_vs_gst_diff: dict = field(default_factory=dict)

    period_count: int = 0
    missing_periods: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gstin": self.gstin,
            "fy": self.fy,
            "total_outward_taxable": self.total_outward_taxable,
            "total_inward_taxable": self.total_inward_taxable,
            "total_itc_claimed": self.total_itc_claimed,
            "total_itc_reversed": self.total_itc_reversed,
            "total_tax_paid": self.total_tax_paid,
            "monthly_breakdown": self.monthly_breakdown,
            "monthly_vs_annual_diff": self.monthly_vs_annual_diff,
            "books_vs_gst_diff": self.books_vs_gst_diff,
            "period_count": self.period_count,
            "missing_periods": self.missing_periods,
        }


async def aggregate_annual(
    user_id: UUID,
    gstin: str,
    fy: str,
    db: AsyncSession,
) -> AnnualReturnData:
    """Aggregate 12 monthly ReturnPeriod records into annual totals.

    Also identifies missing periods and computes discrepancies.
    """
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    repo = ReturnPeriodRepository(db)
    periods = await repo.list_for_fy(user_id, fy)

    result = AnnualReturnData(gstin=gstin, fy=fy)

    # Expected 12 periods (Apr-YYYY to Mar-YYYY+1)
    expected_periods = _fy_expected_periods(fy)
    found_periods = {p.period for p in periods}
    result.missing_periods = [ep for ep in expected_periods if ep not in found_periods]

    cumulative_outward = Decimal("0")
    cumulative_inward = Decimal("0")
    cumulative_itc = Decimal("0")
    cumulative_tax_paid = Decimal("0")

    for p in periods:
        outward = (
            (p.output_tax_igst or Decimal("0"))
            + (p.output_tax_cgst or Decimal("0"))
            + (p.output_tax_sgst or Decimal("0"))
        )
        inward_itc = (
            (p.itc_igst or Decimal("0"))
            + (p.itc_cgst or Decimal("0"))
            + (p.itc_sgst or Decimal("0"))
        )
        net_paid = (
            (p.net_payable_igst or Decimal("0"))
            + (p.net_payable_cgst or Decimal("0"))
            + (p.net_payable_sgst or Decimal("0"))
        )

        cumulative_outward += outward
        cumulative_inward += inward_itc  # Using ITC as proxy for inward
        cumulative_itc += inward_itc
        cumulative_tax_paid += net_paid

        monthly_entry = {
            "period": p.period,
            "status": p.status,
            "outward_taxable": float(outward),
            "itc_claimed": float(inward_itc),
            "net_payable": float(net_paid),
            "outward_count": p.outward_count or 0,
            "inward_count": p.inward_count or 0,
        }
        result.monthly_breakdown.append(monthly_entry)

    result.total_outward_taxable = float(cumulative_outward)
    result.total_inward_taxable = float(cumulative_inward)
    result.total_itc_claimed = float(cumulative_itc)
    result.total_tax_paid = float(cumulative_tax_paid)
    result.period_count = len(periods)

    # Books-vs-GST reconciliation
    books_outward = await _sum_books_outward(user_id, fy, db)
    books_inward = await _sum_books_inward(user_id, fy, db)

    diff_outward = float(books_outward - cumulative_outward)
    diff_inward = float(books_inward - cumulative_itc)

    result.books_vs_gst_diff = {
        "books_outward_taxable": float(books_outward),
        "gst_outward_taxable": result.total_outward_taxable,
        "outward_difference": diff_outward,
        "books_inward_itc": float(books_inward),
        "gst_inward_itc": result.total_itc_claimed,
        "inward_difference": diff_inward,
    }

    # Monthly vs annual consistency check
    for mb in result.monthly_breakdown:
        expected_share = result.total_outward_taxable / 12 if result.total_outward_taxable > 0 else 0
        if expected_share > 0:
            deviation = abs(mb["outward_taxable"] - expected_share) / expected_share * 100
            if deviation > 50:
                result.monthly_vs_annual_diff.append({
                    "period": mb["period"],
                    "deviation_pct": round(deviation, 1),
                    "monthly_value": mb["outward_taxable"],
                    "avg_monthly": round(expected_share, 2),
                    "flag": "significant_deviation",
                })

    # Persist to AnnualReturn table
    await _persist_annual(user_id, gstin, fy, result, db)

    logger.info(
        "Annual return aggregated for %s FY %s: %d periods, outward=₹%.2f, ITC=₹%.2f",
        gstin, fy, result.period_count, result.total_outward_taxable, result.total_itc_claimed,
    )
    return result


async def compute_annual_itc_summary(
    user_id: UUID,
    fy: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Summarize ITC across the year: claimed, eligible, reversed."""
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    repo = ReturnPeriodRepository(db)
    periods = await repo.list_for_fy(user_id, fy)

    total_itc_igst = Decimal("0")
    total_itc_cgst = Decimal("0")
    total_itc_sgst = Decimal("0")

    for p in periods:
        total_itc_igst += p.itc_igst or Decimal("0")
        total_itc_cgst += p.itc_cgst or Decimal("0")
        total_itc_sgst += p.itc_sgst or Decimal("0")

    total_itc = total_itc_igst + total_itc_cgst + total_itc_sgst

    return {
        "fy": fy,
        "itc_igst": float(total_itc_igst),
        "itc_cgst": float(total_itc_cgst),
        "itc_sgst": float(total_itc_sgst),
        "total_itc_claimed": float(total_itc),
        "period_count": len(periods),
    }


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _fy_expected_periods(fy: str) -> list[str]:
    """Return expected 12 YYYY-MM periods for a financial year like '2024-25'."""
    start_year = int(fy.split("-")[0])
    periods = []
    for m in range(4, 13):  # Apr-Dec
        periods.append(f"{start_year}-{m:02d}")
    for m in range(1, 4):  # Jan-Mar
        periods.append(f"{start_year + 1}-{m:02d}")
    return periods


async def _sum_books_outward(user_id: UUID, fy: str, db: AsyncSession) -> Decimal:
    """Sum taxable_value from all outward invoices in the FY."""
    period_range = _fy_expected_periods(fy)
    start_month = period_range[0]  # YYYY-04
    end_month = period_range[-1]   # YYYY+1-03

    start_y, start_m = int(start_month.split("-")[0]), int(start_month.split("-")[1])
    end_y, end_m = int(end_month.split("-")[0]), int(end_month.split("-")[1])

    from datetime import date
    start_date = date(start_y, start_m, 1)
    # End of March
    end_date = date(end_y, end_m, 31)

    stmt = select(func.coalesce(func.sum(Invoice.taxable_value), 0)).where(
        and_(
            Invoice.user_id == user_id,
            Invoice.direction == "outward",
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
        )
    )
    result = await db.execute(stmt)
    return Decimal(str(result.scalar() or 0))


async def _sum_books_inward(user_id: UUID, fy: str, db: AsyncSession) -> Decimal:
    """Sum taxable_value from all inward (purchase) invoices with ITC in the FY."""
    period_range = _fy_expected_periods(fy)
    start_month = period_range[0]
    end_month = period_range[-1]

    start_y, start_m = int(start_month.split("-")[0]), int(start_month.split("-")[1])
    end_y, end_m = int(end_month.split("-")[0]), int(end_month.split("-")[1])

    from datetime import date
    start_date = date(start_y, start_m, 1)
    end_date = date(end_y, end_m, 31)

    stmt = select(func.coalesce(func.sum(Invoice.taxable_value), 0)).where(
        and_(
            Invoice.user_id == user_id,
            Invoice.direction == "inward",
            Invoice.itc_eligible.is_(True),
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
        )
    )
    result = await db.execute(stmt)
    return Decimal(str(result.scalar() or 0))


async def _persist_annual(
    user_id: UUID,
    gstin: str,
    fy: str,
    data: AnnualReturnData,
    db: AsyncSession,
) -> None:
    """Save aggregated data to AnnualReturn table."""
    from app.infrastructure.db.repositories.annual_return_repository import (
        AnnualReturnRepository,
    )

    repo = AnnualReturnRepository(db)
    ar = await repo.create_or_get(user_id, gstin, fy)
    await repo.update_computation(ar.id, {
        "total_outward_taxable": data.total_outward_taxable,
        "total_inward_taxable": data.total_inward_taxable,
        "total_itc_claimed": data.total_itc_claimed,
        "total_itc_reversed": data.total_itc_reversed,
        "total_tax_paid": data.total_tax_paid,
        "monthly_vs_annual_diff": data.monthly_vs_annual_diff,
        "books_vs_gst_diff": data.books_vs_gst_diff,
    })

    # Transition to aggregated if still draft
    if ar.status == "draft":
        await repo.update_status(ar.id, "aggregated")
