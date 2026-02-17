# app/domain/services/gst_itr_linker.py
"""
GST-to-ITR Linker — pulls GST invoice data into ITR-4 (presumptive taxation).

Aggregates turnover from GST invoices for a financial year so business users
can auto-populate their ITR-4 without re-entering data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger("gst_itr_linker")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GSTLinkResult:
    """Aggregated GST data for a financial year, ready for ITR linking."""
    total_turnover: Decimal = Decimal("0")
    total_tax_collected: Decimal = Decimal("0")
    invoice_count: int = 0
    filing_references: list[dict] = field(default_factory=list)
    period_coverage: list[str] = field(default_factory=list)  # e.g. ["2024-04", ...]


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def ay_to_fy(ay: str) -> str:
    """
    Convert Assessment Year to Financial Year.

    "2025-26" → "2024-25"
    """
    parts = ay.split("-")
    if len(parts) == 2:
        start = int(parts[0]) - 1
        end = int(parts[1]) if len(parts[1]) == 2 else int(parts[1]) - 1
        # Handle 2-digit vs 4-digit
        if end > 99:
            end -= 1
        return f"{start}-{end:02d}" if end < 100 else f"{start}-{end}"
    return ay


def fy_to_date_range(fy: str) -> tuple[date, date]:
    """
    Convert Financial Year string to date range.

    "2024-25" → (date(2024, 4, 1), date(2025, 3, 31))
    """
    parts = fy.split("-")
    start_year = int(parts[0])
    return (date(start_year, 4, 1), date(start_year + 1, 3, 31))


# ---------------------------------------------------------------------------
# GST data from WhatsApp session
# ---------------------------------------------------------------------------

def get_gst_data_from_session(
    session: dict[str, Any],
    assessment_year: str = "2025-26",
) -> GSTLinkResult | None:
    """
    Pull GST data from the current WhatsApp session.

    Looks at session["data"]["uploaded_invoices"] and session["data"]["gst_filings"]
    to aggregate turnover for the financial year.

    Parameters
    ----------
    session : dict
        WhatsApp session dict (from Redis).
    assessment_year : str
        Assessment year (e.g. "2025-26").

    Returns
    -------
    GSTLinkResult or None
        None if no invoices found for the FY.
    """
    data = session.get("data", {})
    invoices = data.get("uploaded_invoices", []) + data.get("smart_invoices", [])

    if not invoices:
        return None

    fy = ay_to_fy(assessment_year)
    fy_start, fy_end = fy_to_date_range(fy)

    total_turnover = Decimal("0")
    total_tax = Decimal("0")
    count = 0
    periods: set[str] = set()

    for inv in invoices:
        inv_date = _parse_invoice_date(inv.get("invoice_date"))
        if inv_date and (inv_date < fy_start or inv_date > fy_end):
            continue  # Outside FY range

        taxable = _safe_decimal(inv.get("taxable_value", 0))
        tax = _safe_decimal(inv.get("tax_amount", 0))
        total_turnover += taxable
        total_tax += tax
        count += 1

        if inv_date:
            periods.add(f"{inv_date.year}-{inv_date.month:02d}")

    if count == 0:
        return None

    # Collect GST filing references from session
    filing_refs = []
    for filing in data.get("gst_filings", []):
        filing_refs.append({
            "form_type": filing.get("form_type", ""),
            "period": filing.get("period", ""),
            "reference": filing.get("reference_number", ""),
            "status": filing.get("status", ""),
        })

    return GSTLinkResult(
        total_turnover=total_turnover,
        total_tax_collected=total_tax,
        invoice_count=count,
        filing_references=filing_refs,
        period_coverage=sorted(periods),
    )


# ---------------------------------------------------------------------------
# GST data from database (for CA dashboard / persistent data)
# ---------------------------------------------------------------------------

async def get_gst_data_for_itr(
    user_id: str,
    assessment_year: str,
    db: Any,
) -> GSTLinkResult | None:
    """
    Pull GST data from the database for a user's financial year.

    Parameters
    ----------
    user_id : str
        User UUID.
    assessment_year : str
        Assessment year (e.g. "2025-26").
    db : AsyncSession
        Database session.

    Returns
    -------
    GSTLinkResult or None
    """
    from uuid import UUID as UUIDType
    from sqlalchemy import select
    from app.infrastructure.db.models import Invoice, FilingRecord

    fy = ay_to_fy(assessment_year)
    fy_start, fy_end = fy_to_date_range(fy)

    uid = UUIDType(user_id) if isinstance(user_id, str) else user_id

    # Query invoices for the FY
    stmt = select(Invoice).where(
        Invoice.user_id == uid,
        Invoice.invoice_date >= fy_start,
        Invoice.invoice_date <= fy_end,
    )
    result = await db.execute(stmt)
    invoices = result.scalars().all()

    if not invoices:
        return None

    total_turnover = Decimal("0")
    total_tax = Decimal("0")
    periods: set[str] = set()

    for inv in invoices:
        total_turnover += Decimal(str(inv.taxable_value or 0))
        total_tax += Decimal(str(inv.tax_amount or 0))
        if inv.invoice_date:
            periods.add(f"{inv.invoice_date.year}-{inv.invoice_date.month:02d}")

    # Query GST filing records for the FY months
    fy_months = []
    current = fy_start
    while current <= fy_end:
        fy_months.append(f"{current.year}-{current.month:02d}")
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    filing_stmt = select(FilingRecord).where(
        FilingRecord.user_id == uid,
        FilingRecord.filing_type == "GST",
        FilingRecord.period.in_(fy_months),
    )
    filing_result = await db.execute(filing_stmt)
    filings = filing_result.scalars().all()

    filing_refs = [
        {
            "form_type": f.form_type,
            "period": f.period,
            "reference": f.reference_number or "",
            "status": f.status,
        }
        for f in filings
    ]

    return GSTLinkResult(
        total_turnover=total_turnover,
        total_tax_collected=total_tax,
        invoice_count=len(invoices),
        filing_references=filing_refs,
        period_coverage=sorted(periods),
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def gst_link_to_dict(result: GSTLinkResult) -> dict:
    """Serialize GSTLinkResult to JSON-safe dict."""
    return {
        "total_turnover": str(result.total_turnover),
        "total_tax_collected": str(result.total_tax_collected),
        "invoice_count": result.invoice_count,
        "filing_references": result.filing_references,
        "period_coverage": result.period_coverage,
    }


def dict_to_gst_link(data: dict) -> GSTLinkResult:
    """Deserialize dict to GSTLinkResult."""
    if not data:
        return GSTLinkResult()
    return GSTLinkResult(
        total_turnover=_safe_decimal(data.get("total_turnover", 0)),
        total_tax_collected=_safe_decimal(data.get("total_tax_collected", 0)),
        invoice_count=data.get("invoice_count", 0),
        filing_references=data.get("filing_references", []),
        period_coverage=data.get("period_coverage", []),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_decimal(val: Any) -> Decimal:
    """Safely convert a value to Decimal."""
    if val is None:
        return Decimal("0")
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_invoice_date(val: Any) -> date | None:
    """Parse invoice date from various formats."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None
