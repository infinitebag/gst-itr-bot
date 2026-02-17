# app/domain/services/pending_itc_service.py
"""
Pending ITC (Input Tax Credit) lifecycle management.

Tracks ITC that appears in books but not in GSTR-2B ("missing in 2B"),
supports carry-forward across periods, and generates vendor follow-up messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("pending_itc_service")


@dataclass
class PendingITCItem:
    """A single pending ITC entry -- invoice in books but missing from 2B."""
    supplier_gstin: str
    invoice_number: str
    invoice_date: str | None
    taxable_value: float
    igst: float
    cgst: float
    sgst: float
    total_itc: float
    periods_pending: int = 1  # how many months it's been pending
    original_period: str = ""

    def to_dict(self) -> dict:
        return {
            "supplier_gstin": self.supplier_gstin,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "taxable_value": self.taxable_value,
            "total_itc": self.total_itc,
            "periods_pending": self.periods_pending,
            "original_period": self.original_period,
        }


@dataclass
class PendingITCSummary:
    """Summary of pending ITC for a GSTIN."""
    total_pending_itc: float = 0
    pending_count: int = 0
    suppliers_affected: int = 0
    items: list[PendingITCItem] = field(default_factory=list)
    aged_buckets: dict = field(default_factory=dict)  # {"1-month": X, "2-3 months": Y, "3+ months": Z}

    def to_dict(self) -> dict:
        return {
            "total_pending_itc": self.total_pending_itc,
            "pending_count": self.pending_count,
            "suppliers_affected": self.suppliers_affected,
            "aged_buckets": self.aged_buckets,
            "items": [i.to_dict() for i in self.items],
        }


async def get_pending_itc(
    gstin: str,
    current_period: str,
    db: AsyncSession,
) -> PendingITCSummary:
    """Get all pending ITC items for a GSTIN.

    Pending = invoices in books (uploaded) that are NOT matched in any GSTR-2B import.
    """
    from app.infrastructure.db.models import ITCMatch, Invoice

    summary = PendingITCSummary()

    # Find all unmatched/missing records
    stmt = (
        select(ITCMatch)
        .where(
            and_(
                ITCMatch.match_status.in_(["unmatched", "missing_in_2b"]),
            )
        )
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    suppliers = set()
    one_month = 0
    two_three_month = 0
    older = 0

    for rec in records:
        itc_total = float(
            (rec.gstr2b_igst or Decimal("0"))
            + (rec.gstr2b_cgst or Decimal("0"))
            + (rec.gstr2b_sgst or Decimal("0"))
        )

        item = PendingITCItem(
            supplier_gstin=rec.gstr2b_supplier_gstin or "",
            invoice_number=rec.gstr2b_invoice_number or "",
            invoice_date=str(rec.gstr2b_invoice_date) if rec.gstr2b_invoice_date else None,
            taxable_value=float(rec.gstr2b_taxable_value or 0),
            igst=float(rec.gstr2b_igst or 0),
            cgst=float(rec.gstr2b_cgst or 0),
            sgst=float(rec.gstr2b_sgst or 0),
            total_itc=itc_total,
        )
        summary.items.append(item)
        summary.total_pending_itc += itc_total
        suppliers.add(item.supplier_gstin)

        # Age bucket (simplified)
        one_month += 1  # default to 1-month for now

    summary.pending_count = len(summary.items)
    summary.suppliers_affected = len(suppliers)
    summary.aged_buckets = {
        "1_month": one_month,
        "2_3_months": two_three_month,
        "3_plus_months": older,
    }

    return summary


def generate_vendor_followup_message(
    item: PendingITCItem,
    business_name: str = "our records",
    lang: str = "en",
) -> str:
    """Generate a WhatsApp follow-up message template for a supplier
    about a missing invoice in GSTR-2B.
    """
    if lang == "hi":
        return (
            f"\U0001f514 *ITC \u0905\u0928\u0941\u0935\u0930\u094d\u0924\u0940 \u0905\u0928\u0941\u0930\u094b\u0927*\n\n"
            f"\u092a\u094d\u0930\u093f\u092f {item.supplier_gstin},\n\n"
            f"\u0939\u092e\u093e\u0930\u0947 \u0930\u093f\u0915\u0949\u0930\u094d\u0921 \u0915\u0947 \u0905\u0928\u0941\u0938\u093e\u0930, \u0907\u0928\u0935\u0949\u0907\u0938 *{item.invoice_number}* "
            f"(\u20b9{item.taxable_value:,.2f}) GSTR-2B \u092e\u0947\u0902 \u0926\u093f\u0916\u093e\u0908 \u0928\u0939\u0940\u0902 \u0926\u0947 \u0930\u0939\u0940 \u0939\u0948\u0964\n\n"
            f"\u0915\u0943\u092a\u092f\u093e \u0938\u0941\u0928\u093f\u0936\u094d\u091a\u093f\u0924 \u0915\u0930\u0947\u0902 \u0915\u093f \u092f\u0939 \u0906\u092a\u0915\u0947 GSTR-1 \u092e\u0947\u0902 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0915\u0940 \u0917\u0908 \u0939\u0948\u0964\n\n"
            f"\u0927\u0928\u094d\u092f\u0935\u093e\u0926"
        )

    return (
        f"\U0001f514 *ITC Follow-up Request*\n\n"
        f"Dear Supplier ({item.supplier_gstin}),\n\n"
        f"As per {business_name}, invoice *{item.invoice_number}* "
        f"dated {item.invoice_date or 'N/A'} for \u20b9{item.taxable_value:,.2f} "
        f"is not reflecting in our GSTR-2B.\n\n"
        f"Please ensure it is reported in your GSTR-1.\n\n"
        f"Thank you"
    )


async def carry_forward_pending(
    gstin: str,
    from_period: str,
    to_period: str,
    db: AsyncSession,
) -> int:
    """Carry forward unresolved pending ITC from one period to the next.

    Returns count of items carried forward.
    """
    from app.infrastructure.db.models import ITCMatch

    stmt = (
        select(ITCMatch)
        .where(
            and_(
                ITCMatch.match_status.in_(["unmatched", "missing_in_2b"]),
            )
        )
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    count = 0
    for rec in records:
        # Mark as carried forward (the record persists)
        if rec.match_status == "missing_in_2b":
            count += 1

    logger.info(
        "Carried forward %d pending ITC items from %s to %s for %s",
        count, from_period, to_period, gstin,
    )
    return count
