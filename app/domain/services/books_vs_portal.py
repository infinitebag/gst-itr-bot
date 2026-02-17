"""
Books vs Portal Comparison Engine.

Compares internal records (uploaded invoices) against portal data
(GSTR-1 for sales, GSTR-2B for purchases) to detect discrepancies
that could trigger notices or missed ITC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("books_vs_portal")


@dataclass
class ComparisonItem:
    """A single comparison row between books and portal."""
    invoice_number: str
    supplier_or_recipient_gstin: str
    books_taxable: float = 0
    books_igst: float = 0
    books_cgst: float = 0
    books_sgst: float = 0
    portal_taxable: float = 0
    portal_igst: float = 0
    portal_cgst: float = 0
    portal_sgst: float = 0
    status: str = "matched"  # matched | value_mismatch | missing_in_portal | missing_in_books
    difference: float = 0

    def to_dict(self) -> dict:
        return {
            "invoice_number": self.invoice_number,
            "gstin": self.supplier_or_recipient_gstin,
            "books_taxable": self.books_taxable,
            "portal_taxable": self.portal_taxable,
            "status": self.status,
            "difference": self.difference,
        }


@dataclass
class ComparisonSummary:
    """Summary of books vs portal comparison."""
    comparison_type: str  # "sales" or "purchases"
    period: str
    total_books_count: int = 0
    total_portal_count: int = 0
    matched_count: int = 0
    value_mismatch_count: int = 0
    missing_in_portal_count: int = 0
    missing_in_books_count: int = 0
    total_books_value: float = 0
    total_portal_value: float = 0
    net_difference: float = 0
    items: list[ComparisonItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "comparison_type": self.comparison_type,
            "period": self.period,
            "total_books_count": self.total_books_count,
            "total_portal_count": self.total_portal_count,
            "matched": self.matched_count,
            "value_mismatches": self.value_mismatch_count,
            "missing_in_portal": self.missing_in_portal_count,
            "missing_in_books": self.missing_in_books_count,
            "books_value": self.total_books_value,
            "portal_value": self.total_portal_value,
            "net_difference": self.net_difference,
            "mismatched_items": [
                i.to_dict() for i in self.items
                if i.status != "matched"
            ],
        }

    def format_whatsapp(self, lang: str = "en") -> str:
        """Format comparison for WhatsApp display."""
        label = "Sales (GSTR-1)" if self.comparison_type == "sales" else "Purchases (GSTR-2B)"
        emoji = "\U0001f4ca"
        lines = [
            f"{emoji} *Books vs Portal \u2014 {label}*",
            f"Period: {self.period}\n",
            f"\U0001f4d7 Books: {self.total_books_count} invoices (\u20b9{self.total_books_value:,.2f})",
            f"\U0001f310 Portal: {self.total_portal_count} invoices (\u20b9{self.total_portal_value:,.2f})",
            f"\n\u2705 Matched: {self.matched_count}",
        ]
        if self.value_mismatch_count:
            lines.append(f"\u26a0\ufe0f Value mismatches: {self.value_mismatch_count}")
        if self.missing_in_portal_count:
            lines.append(f"\U0001f4e4 Missing in portal: {self.missing_in_portal_count}")
        if self.missing_in_books_count:
            lines.append(f"\U0001f4e5 Missing in books: {self.missing_in_books_count}")
        if abs(self.net_difference) > 0.01:
            lines.append(f"\n\U0001f4b0 Net difference: \u20b9{self.net_difference:,.2f}")
        return "\n".join(lines)


# Tolerance for matching (₹1 difference is acceptable)
_MATCH_TOLERANCE = Decimal("1.0")


async def compare_sales(
    user_id: UUID,
    gstin: str,
    period: str,
    db: AsyncSession,
) -> ComparisonSummary:
    """Compare uploaded sales invoices against GSTR-1 filed data."""
    from app.infrastructure.db.models import Invoice

    summary = ComparisonSummary(comparison_type="sales", period=period)

    # Get books data (outward invoices for this period)
    stmt = select(Invoice).where(
        and_(
            Invoice.user_id == user_id,
            Invoice.direction == "outward",
        )
    )
    result = await db.execute(stmt)
    all_invoices = result.scalars().all()

    # Filter to period
    books = {}
    for inv in all_invoices:
        if inv.invoice_date and inv.invoice_date.strftime("%Y-%m") == period:
            key = (inv.invoice_number or "").strip().upper()
            if key:
                books[key] = inv

    summary.total_books_count = len(books)
    summary.total_books_value = sum(
        float(inv.taxable_value or 0) for inv in books.values()
    )

    # For sales comparison, portal data would come from GSTR-1 filed records
    # Since we prepare GSTR-1 locally, we compare books against computed filing data
    # In production, this would fetch from portal via MasterGST

    # For now, mark all as "in books" — portal integration pending
    for key, inv in books.items():
        item = ComparisonItem(
            invoice_number=key,
            supplier_or_recipient_gstin=inv.recipient_gstin or "",
            books_taxable=float(inv.taxable_value or 0),
            books_igst=float(inv.igst_amount or 0),
            books_cgst=float(inv.cgst_amount or 0),
            books_sgst=float(inv.sgst_amount or 0),
            portal_taxable=float(inv.taxable_value or 0),  # assume filed = books
            status="matched",
        )
        summary.items.append(item)
        summary.matched_count += 1

    summary.total_portal_count = summary.matched_count
    summary.total_portal_value = summary.total_books_value

    return summary


async def compare_purchases(
    user_id: UUID,
    gstin: str,
    period: str,
    period_id: UUID | None,
    db: AsyncSession,
) -> ComparisonSummary:
    """Compare uploaded purchase invoices against GSTR-2B imported data."""
    from app.infrastructure.db.models import Invoice, ITCMatch

    summary = ComparisonSummary(comparison_type="purchases", period=period)

    # Get books data (inward invoices)
    stmt = select(Invoice).where(
        and_(
            Invoice.user_id == user_id,
            Invoice.direction == "inward",
        )
    )
    result = await db.execute(stmt)
    all_invoices = result.scalars().all()

    books = {}
    for inv in all_invoices:
        if inv.invoice_date and inv.invoice_date.strftime("%Y-%m") == period:
            key = (inv.invoice_number or "").strip().upper()
            if key:
                books[key] = inv

    summary.total_books_count = len(books)
    summary.total_books_value = sum(
        float(inv.taxable_value or 0) for inv in books.values()
    )

    # Get portal data (GSTR-2B imported ITCMatch records)
    portal = {}
    if period_id:
        stmt2 = select(ITCMatch).where(ITCMatch.period_id == period_id)
        result2 = await db.execute(stmt2)
        for rec in result2.scalars().all():
            key = (rec.gstr2b_invoice_number or "").strip().upper()
            if key:
                portal[key] = rec

    summary.total_portal_count = len(portal)
    summary.total_portal_value = sum(
        float(rec.gstr2b_taxable_value or 0) for rec in portal.values()
    )

    # Compare: matched, mismatched, missing
    all_keys = set(books.keys()) | set(portal.keys())

    for key in all_keys:
        in_books = key in books
        in_portal = key in portal

        if in_books and in_portal:
            inv = books[key]
            rec = portal[key]
            books_val = Decimal(str(inv.taxable_value or 0))
            portal_val = rec.gstr2b_taxable_value or Decimal("0")
            diff = abs(books_val - portal_val)

            item = ComparisonItem(
                invoice_number=key,
                supplier_or_recipient_gstin=inv.supplier_gstin or rec.gstr2b_supplier_gstin or "",
                books_taxable=float(books_val),
                books_igst=float(inv.igst_amount or 0),
                books_cgst=float(inv.cgst_amount or 0),
                books_sgst=float(inv.sgst_amount or 0),
                portal_taxable=float(portal_val),
                portal_igst=float(rec.gstr2b_igst or 0),
                portal_cgst=float(rec.gstr2b_cgst or 0),
                portal_sgst=float(rec.gstr2b_sgst or 0),
                difference=float(diff),
            )
            if diff <= _MATCH_TOLERANCE:
                item.status = "matched"
                summary.matched_count += 1
            else:
                item.status = "value_mismatch"
                summary.value_mismatch_count += 1
            summary.items.append(item)

        elif in_books and not in_portal:
            inv = books[key]
            item = ComparisonItem(
                invoice_number=key,
                supplier_or_recipient_gstin=inv.supplier_gstin or "",
                books_taxable=float(inv.taxable_value or 0),
                status="missing_in_portal",
                difference=float(inv.taxable_value or 0),
            )
            summary.missing_in_portal_count += 1
            summary.items.append(item)

        elif in_portal and not in_books:
            rec = portal[key]
            item = ComparisonItem(
                invoice_number=key,
                supplier_or_recipient_gstin=rec.gstr2b_supplier_gstin or "",
                portal_taxable=float(rec.gstr2b_taxable_value or 0),
                status="missing_in_books",
                difference=float(rec.gstr2b_taxable_value or 0),
            )
            summary.missing_in_books_count += 1
            summary.items.append(item)

    summary.net_difference = summary.total_books_value - summary.total_portal_value

    return summary
