# app/domain/services/gst_itr_recon.py
"""
GST-to-ITR Turnover Reconciliation.

Compares total outward taxable turnover from GST ReturnPeriods against
ITR-reported turnover for the same financial year. Identifies discrepancies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

logger = logging.getLogger("gst_itr_recon")

ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TurnoverReconResult:
    """Result of GST vs ITR turnover reconciliation."""
    fy: str = ""
    gst_turnover: Decimal = ZERO
    itr_turnover: Decimal = ZERO
    variance: Decimal = ZERO
    variance_pct: Decimal = ZERO
    status: str = "not_available"  # ok / needs_explanation / high_risk / not_available
    periods_with_data: int = 0
    total_periods: int = 0
    notes: list[str] | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def reconcile_turnover(
    user_id: UUID,
    fy: str,
    db: Any,
) -> TurnoverReconResult:
    """
    Compare GST outward turnover against ITR-reported turnover for a FY.

    Steps:
    1. Sum all ReturnPeriod outward taxable values across FY periods
    2. Query ITRDraft for matching assessment year
    3. Compute variance and classify

    Classification:
    - variance_pct <= 2%: ok
    - 2% < variance_pct <= 5%: needs_explanation
    - variance_pct > 5%: high_risk

    Parameters
    ----------
    user_id : UUID
    fy : str
        Financial year in "YYYY-YY" format, e.g. "2024-25"
    db : AsyncSession

    Returns
    -------
    TurnoverReconResult
    """
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository

    period_repo = ReturnPeriodRepository(db)
    periods = await period_repo.list_for_fy(user_id, fy)

    result = TurnoverReconResult(fy=fy, total_periods=12)

    if not periods:
        result.notes = ["No GST return periods found for this financial year."]
        return result

    # -------------------------------------------------------------------
    # 1. Sum GST outward turnover from ReturnPeriod records
    # -------------------------------------------------------------------
    gst_turnover = ZERO
    periods_with_data = 0

    for p in periods:
        # Sum outward tax as a proxy for taxable value
        # The actual outward taxable value is output tax aggregates
        # We use the period's computed output tax totals
        period_output = (
            _dec(p.output_tax_igst)
            + _dec(p.output_tax_cgst)
            + _dec(p.output_tax_sgst)
        )
        if period_output > ZERO or p.outward_count > 0:
            periods_with_data += 1

        # For turnover, we need actual taxable value, not just tax.
        # Use invoice aggregation for accurate turnover.
        gst_turnover += await _sum_outward_taxable(user_id, p.period, db)

    result.gst_turnover = gst_turnover
    result.periods_with_data = periods_with_data

    # -------------------------------------------------------------------
    # 2. Get ITR-reported turnover
    # -------------------------------------------------------------------
    ay = _fy_to_ay(fy)
    itr_turnover = await _get_itr_turnover(user_id, ay, db)

    if itr_turnover is None:
        result.status = "not_available"
        result.notes = [
            f"ITR data for AY {ay} not found. File ITR first to enable turnover reconciliation."
        ]
        return result

    result.itr_turnover = itr_turnover

    # -------------------------------------------------------------------
    # 3. Compute variance
    # -------------------------------------------------------------------
    result.variance = abs(result.gst_turnover - result.itr_turnover)

    if result.itr_turnover > ZERO:
        result.variance_pct = (result.variance / result.itr_turnover) * Decimal("100")
    elif result.gst_turnover > ZERO:
        result.variance_pct = Decimal("100")  # ITR says 0 but GST has turnover
    else:
        result.variance_pct = ZERO

    # Classify
    if result.variance_pct <= Decimal("2"):
        result.status = "ok"
    elif result.variance_pct <= Decimal("5"):
        result.status = "needs_explanation"
        result.notes = [
            f"Variance of {result.variance_pct:.1f}% between GST and ITR turnover. "
            "Minor differences may be due to timing, credit notes, or rounding."
        ]
    else:
        result.status = "high_risk"
        result.notes = [
            f"Variance of {result.variance_pct:.1f}% between GST and ITR turnover. "
            "This exceeds the safe threshold and may attract scrutiny. "
            "Please verify with your CA."
        ]

    logger.info(
        "Turnover recon: fy=%s, gst=%.2f, itr=%.2f, variance=%.2f (%.1f%%), status=%s",
        fy, result.gst_turnover, result.itr_turnover,
        result.variance, result.variance_pct, result.status,
    )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fy_to_ay(fy: str) -> str:
    """Convert FY '2024-25' to AY '2025-26'."""
    parts = fy.split("-")
    start_year = int(parts[0])
    end_suffix = int(parts[1]) if len(parts[1]) == 2 else int(parts[1]) % 100
    return f"{start_year + 1}-{end_suffix + 1:02d}"


async def _sum_outward_taxable(user_id: UUID, period: str, db: Any) -> Decimal:
    """Sum taxable_value of all outward invoices for a period."""
    from calendar import monthrange
    from datetime import date

    from app.infrastructure.db.repositories.invoice_repository import InvoiceRepository

    parts = period.split("-")
    year, month = int(parts[0]), int(parts[1])
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    inv_repo = InvoiceRepository(db)
    invoices = await inv_repo.list_for_period_by_direction(
        user_id, start, end, "outward"
    )

    total = ZERO
    for inv in invoices:
        total += _dec(inv.taxable_value)
    return total


async def _get_itr_turnover(user_id: UUID, ay: str, db: Any) -> Decimal | None:
    """
    Get ITR-reported turnover for an assessment year.
    Returns None if no ITR data found.
    """
    import json

    from sqlalchemy import select
    from app.infrastructure.db.models import FilingRecord

    # Look for ITR filing records with the matching assessment year
    stmt = (
        select(FilingRecord)
        .where(
            FilingRecord.user_id == user_id,
            FilingRecord.filing_type == "ITR",
            FilingRecord.period == ay,
        )
        .order_by(FilingRecord.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    filing = result.scalar_one_or_none()

    if not filing:
        return None

    # Extract turnover from payload
    payload = {}
    if filing.payload_json:
        try:
            payload = json.loads(filing.payload_json)
        except (ValueError, TypeError):
            return None

    # Try different payload structures
    # ITR-4: gross_turnover or total_turnover
    # ITR-1/2: salary + business income, etc.
    turnover = (
        payload.get("gross_turnover")
        or payload.get("total_turnover")
        or payload.get("business_income")
    )

    if turnover is not None:
        return _dec(turnover)

    return None


def _dec(val: Any) -> Decimal:
    """Safely convert to Decimal."""
    if val is None:
        return ZERO
    try:
        return Decimal(str(val))
    except Exception:
        return ZERO


# ---------------------------------------------------------------------------
# Phase 2: Detailed period-level reconciliation
# ---------------------------------------------------------------------------

@dataclass
class PeriodReconEntry:
    """Single period entry in detailed reconciliation."""
    period: str = ""
    gst_outward_taxable: Decimal = ZERO
    gst_credit_notes: Decimal = ZERO
    gst_net_taxable: Decimal = ZERO
    gst_exempt_nil: Decimal = ZERO
    books_turnover: Decimal = ZERO
    variance: Decimal = ZERO
    variance_pct: Decimal = ZERO
    status: str = "ok"


@dataclass
class DetailedReconResult:
    """Result of detailed period-level GST↔ITR reconciliation."""
    fy: str = ""
    summary: TurnoverReconResult | None = None
    period_details: list[PeriodReconEntry] = None  # type: ignore[assignment]
    total_credit_notes: Decimal = ZERO
    total_exempt_nil: Decimal = ZERO
    adjusted_gst_turnover: Decimal = ZERO
    notes: list[str] | None = None

    def __post_init__(self) -> None:
        if self.period_details is None:
            self.period_details = []

    def to_dict(self) -> dict:
        return {
            "fy": self.fy,
            "summary": {
                "gst_turnover": float(self.summary.gst_turnover) if self.summary else 0,
                "itr_turnover": float(self.summary.itr_turnover) if self.summary else 0,
                "variance": float(self.summary.variance) if self.summary else 0,
                "variance_pct": float(self.summary.variance_pct) if self.summary else 0,
                "status": self.summary.status if self.summary else "not_available",
            },
            "total_credit_notes": float(self.total_credit_notes),
            "total_exempt_nil": float(self.total_exempt_nil),
            "adjusted_gst_turnover": float(self.adjusted_gst_turnover),
            "period_details": [
                {
                    "period": pd.period,
                    "gst_outward_taxable": float(pd.gst_outward_taxable),
                    "gst_credit_notes": float(pd.gst_credit_notes),
                    "gst_net_taxable": float(pd.gst_net_taxable),
                    "gst_exempt_nil": float(pd.gst_exempt_nil),
                    "books_turnover": float(pd.books_turnover),
                    "variance": float(pd.variance),
                    "variance_pct": float(pd.variance_pct),
                    "status": pd.status,
                }
                for pd in self.period_details
            ],
            "notes": self.notes,
        }


async def reconcile_turnover_detailed(
    user_id: UUID,
    fy: str,
    db: Any,
) -> DetailedReconResult:
    """Detailed period-by-period GST↔ITR turnover reconciliation.

    Enhancements over basic reconcile_turnover():
    - Per-month breakdown
    - Credit note adjustments
    - Exempt / nil-rated supply tracking
    - Books-vs-GST comparison per period
    """
    from calendar import monthrange
    from datetime import date
    from sqlalchemy import and_, func, select
    from app.infrastructure.db.models import Invoice
    from app.infrastructure.db.repositories.return_period_repository import (
        ReturnPeriodRepository,
    )

    # First, run summary reconciliation
    summary = await reconcile_turnover(user_id, fy, db)

    result = DetailedReconResult(fy=fy, summary=summary)

    period_repo = ReturnPeriodRepository(db)
    periods = await period_repo.list_for_fy(user_id, fy)

    total_credit_notes = ZERO
    total_exempt_nil = ZERO
    total_adjusted = ZERO

    for p in periods:
        entry = PeriodReconEntry(period=p.period)

        # GST outward taxable from invoices
        entry.gst_outward_taxable = await _sum_outward_taxable(user_id, p.period, db)

        # Credit notes for the period (negative taxable_value or total_amount)
        parts = p.period.split("-")
        year, month = int(parts[0]), int(parts[1])
        period_start = date(year, month, 1)
        period_end = date(year, month, monthrange(year, month)[1])

        cn_stmt = select(func.coalesce(func.sum(Invoice.taxable_value), 0)).where(
            and_(
                Invoice.user_id == user_id,
                Invoice.direction == "outward",
                Invoice.invoice_date >= period_start,
                Invoice.invoice_date <= period_end,
                Invoice.taxable_value < 0,
            )
        )
        cn_result = await db.execute(cn_stmt)
        entry.gst_credit_notes = abs(_dec(cn_result.scalar()))

        # Exempt / nil-rated supplies (tax_rate == 0 but positive taxable_value)
        exempt_stmt = select(func.coalesce(func.sum(Invoice.taxable_value), 0)).where(
            and_(
                Invoice.user_id == user_id,
                Invoice.direction == "outward",
                Invoice.invoice_date >= period_start,
                Invoice.invoice_date <= period_end,
                Invoice.tax_rate == 0,
                Invoice.taxable_value > 0,
            )
        )
        exempt_result = await db.execute(exempt_stmt)
        entry.gst_exempt_nil = _dec(exempt_result.scalar())

        entry.gst_net_taxable = entry.gst_outward_taxable - entry.gst_credit_notes
        entry.books_turnover = entry.gst_net_taxable  # Default to GST data

        entry.variance = abs(entry.gst_net_taxable - entry.books_turnover)
        if entry.books_turnover > ZERO:
            entry.variance_pct = (entry.variance / entry.books_turnover) * Decimal("100")
        entry.status = "ok"  # Will be refined with books integration

        result.period_details.append(entry)
        total_credit_notes += entry.gst_credit_notes
        total_exempt_nil += entry.gst_exempt_nil
        total_adjusted += entry.gst_net_taxable

    result.total_credit_notes = total_credit_notes
    result.total_exempt_nil = total_exempt_nil
    result.adjusted_gst_turnover = total_adjusted

    # Notes
    notes = []
    if total_credit_notes > ZERO:
        notes.append(
            f"Total credit notes: ₹{total_credit_notes:,.2f} "
            "(already adjusted from gross turnover)"
        )
    if total_exempt_nil > ZERO:
        notes.append(
            f"Exempt/nil-rated supplies: ₹{total_exempt_nil:,.2f} "
            "(not subject to GST but included in ITR turnover)"
        )
    if result.summary and result.summary.status != "ok":
        notes.append(
            "Consider timing differences between GST filing and books closing dates."
        )
    result.notes = notes if notes else None

    logger.info(
        "Detailed recon: fy=%s, periods=%d, credit_notes=₹%.2f, exempt=₹%.2f, adjusted=₹%.2f",
        fy, len(result.period_details), total_credit_notes, total_exempt_nil, total_adjusted,
    )
    return result
