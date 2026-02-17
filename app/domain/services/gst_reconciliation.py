# app/domain/services/gst_reconciliation.py
"""
ITC Reconciliation Engine.

Matches purchase invoices in the books against GSTR-2B entries
to identify matched, mismatched, and missing records.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

logger = logging.getLogger("gst_reconciliation")

# Tolerance for value matching (Rs 1)
VALUE_TOLERANCE = Decimal("1.00")
# Tolerance for date matching (5 days)
DATE_TOLERANCE_DAYS = 5


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReconciliationSummary:
    """Summary of ITC reconciliation results."""
    total_2b_entries: int = 0
    total_book_entries: int = 0
    matched: int = 0
    value_mismatch: int = 0
    missing_in_2b: int = 0
    missing_in_books: int = 0
    matched_taxable: Decimal = Decimal("0")
    matched_tax: Decimal = Decimal("0")
    mismatch_taxable_diff: Decimal = Decimal("0")
    missing_in_2b_taxable: Decimal = Decimal("0")
    missing_in_books_taxable: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def reconcile_period(period_id: UUID, db: Any) -> ReconciliationSummary:
    """
    Core reconciliation algorithm.

    1. Load all inward invoices for the period from the books
    2. Load all ITCMatch records (GSTR-2B entries) for the period
    3. Build lookup index on normalized (supplier_gstin, invoice_number)
    4. For each 2B entry, find best matching book invoice
    5. Classify: matched / value_mismatch / missing_in_books / missing_in_2b
    6. Update both Invoice.gstr2b_match_status and ITCMatch fields
    7. Return ReconciliationSummary
    """
    from calendar import monthrange

    from app.infrastructure.db.repositories.itc_match_repository import ITCMatchRepository
    from app.infrastructure.db.repositories.invoice_repository import InvoiceRepository
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository

    period_repo = ReturnPeriodRepository(db)
    period_rec = await period_repo.get_by_id(period_id)
    if not period_rec:
        raise ValueError(f"ReturnPeriod {period_id} not found")

    # Date range for the period
    parts = period_rec.period.split("-")
    year, month = int(parts[0]), int(parts[1])
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    # Load book invoices (inward only)
    inv_repo = InvoiceRepository(db)
    book_invoices = await inv_repo.list_for_period_by_direction(
        period_rec.user_id, start, end, "inward"
    )

    # Load 2B entries
    match_repo = ITCMatchRepository(db)
    twob_entries = await match_repo.list_for_period(period_id)

    # Build book index: normalized_key -> list[Invoice]
    book_index: dict[str, list] = {}
    for inv in book_invoices:
        key = _normalize_match_key(inv.supplier_gstin, inv.invoice_number)
        book_index.setdefault(key, []).append(inv)

    summary = ReconciliationSummary(
        total_2b_entries=len(twob_entries),
        total_book_entries=len(book_invoices),
    )

    matched_book_ids: set = set()

    for entry in twob_entries:
        key = _normalize_match_key(
            entry.gstr2b_supplier_gstin, entry.gstr2b_invoice_number
        )
        candidates = book_index.get(key, [])
        best_match = _find_best_match(entry, candidates, matched_book_ids)

        if best_match is None:
            # Missing in books (excess in 2B)
            entry.match_status = "missing_in_books"
            summary.missing_in_books += 1
            summary.missing_in_books_taxable += entry.gstr2b_taxable_value or Decimal("0")
        else:
            matched_book_ids.add(best_match.id)
            entry.purchase_invoice_id = best_match.id

            if _values_match(entry, best_match):
                entry.match_status = "matched"
                best_match.gstr2b_match_status = "matched"
                best_match.gstr2b_match_id = entry.id
                summary.matched += 1
                summary.matched_taxable += entry.gstr2b_taxable_value or Decimal("0")
                summary.matched_tax += (
                    (entry.gstr2b_igst or Decimal("0"))
                    + (entry.gstr2b_cgst or Decimal("0"))
                    + (entry.gstr2b_sgst or Decimal("0"))
                )
            else:
                details = _build_mismatch_details(entry, best_match)
                entry.match_status = "value_mismatch"
                entry.mismatch_details = json.dumps(details)
                best_match.gstr2b_match_status = "mismatch"
                best_match.gstr2b_match_id = entry.id
                summary.value_mismatch += 1
                summary.mismatch_taxable_diff += abs(
                    (entry.gstr2b_taxable_value or Decimal("0"))
                    - Decimal(str(best_match.taxable_value or 0))
                )

    # Remaining unmatched book invoices -> missing_in_2b
    for inv in book_invoices:
        if inv.id not in matched_book_ids:
            inv.gstr2b_match_status = "missing_in_2b"
            summary.missing_in_2b += 1
            summary.missing_in_2b_taxable += Decimal(str(inv.taxable_value or 0))

    await db.commit()

    # Update period status to reconciled
    try:
        await period_repo.update_status(period_id, "reconciled")
    except Exception:
        # Status transition may fail if not in valid state — log but don't crash
        logger.warning(
            "Could not transition period %s to 'reconciled' — current status may not allow it",
            period_id,
        )

    logger.info(
        "Reconciliation done: period=%s, matched=%d, mismatch=%d, "
        "missing_in_2b=%d, missing_in_books=%d",
        period_rec.period, summary.matched, summary.value_mismatch,
        summary.missing_in_2b, summary.missing_in_books,
    )

    return summary


async def get_reconciliation_summary(period_id: UUID, db: Any) -> dict:
    """Read-only reconciliation summary via ITCMatchRepository.get_summary()."""
    from app.infrastructure.db.repositories.itc_match_repository import ITCMatchRepository
    repo = ITCMatchRepository(db)
    return await repo.get_summary(period_id)


async def get_mismatches(period_id: UUID, db: Any) -> list:
    """Get all ITCMatch entries with status other than 'matched'."""
    from app.infrastructure.db.repositories.itc_match_repository import ITCMatchRepository
    repo = ITCMatchRepository(db)

    results = []
    for status in ("value_mismatch", "missing_in_books", "missing_in_2b"):
        entries = await repo.list_for_period(period_id, status=status)
        results.extend(entries)
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_match_key(gstin: str | None, inv_num: str | None) -> str:
    """Create a normalized lookup key from GSTIN + invoice number.

    Normalization:
    - Uppercase
    - Strip leading zeros from invoice number
    - Remove common separators (-, /, spaces)
    """
    g = (gstin or "").strip().upper()
    n = (inv_num or "").strip().upper().lstrip("0")
    # Remove common separators for fuzzy matching
    n = n.replace("-", "").replace("/", "").replace(" ", "").replace("\\", "")
    return f"{g}|{n}"


def _find_best_match(entry, candidates: list, already_matched_ids: set) -> Any | None:
    """Find the best matching book invoice for a 2B entry."""
    available = [c for c in candidates if c.id not in already_matched_ids]
    if not available:
        return None
    if len(available) == 1:
        return available[0]

    # Multiple candidates: prefer closest date
    entry_date = entry.gstr2b_invoice_date
    if not entry_date:
        return available[0]  # no date to compare, take first

    best = None
    best_diff = timedelta(days=999)
    for inv in available:
        if inv.invoice_date:
            diff = abs(inv.invoice_date - entry_date)
            if diff < best_diff:
                best_diff = diff
                best = inv

    return best or available[0]


def _values_match(entry, invoice) -> bool:
    """Check if taxable and tax values are within tolerance (±Rs 1)."""
    tv_diff = abs(
        (entry.gstr2b_taxable_value or Decimal("0"))
        - Decimal(str(invoice.taxable_value or 0))
    )
    igst_diff = abs(
        (entry.gstr2b_igst or Decimal("0"))
        - Decimal(str(invoice.igst_amount or 0))
    )
    cgst_diff = abs(
        (entry.gstr2b_cgst or Decimal("0"))
        - Decimal(str(invoice.cgst_amount or 0))
    )
    sgst_diff = abs(
        (entry.gstr2b_sgst or Decimal("0"))
        - Decimal(str(invoice.sgst_amount or 0))
    )
    return all(d <= VALUE_TOLERANCE for d in [tv_diff, igst_diff, cgst_diff, sgst_diff])


def _build_mismatch_details(entry, invoice) -> dict:
    """Build a JSON-serializable dict of field-level differences."""
    details: dict = {}

    book_tv = float(invoice.taxable_value or 0)
    twob_tv = float(entry.gstr2b_taxable_value or 0)
    if abs(twob_tv - book_tv) > float(VALUE_TOLERANCE):
        details["taxable_value"] = {"books": book_tv, "2b": twob_tv}

    for field_name, book_attr, twob_attr in [
        ("igst", "igst_amount", "gstr2b_igst"),
        ("cgst", "cgst_amount", "gstr2b_cgst"),
        ("sgst", "sgst_amount", "gstr2b_sgst"),
    ]:
        book_val = float(getattr(invoice, book_attr, None) or 0)
        twob_val = float(getattr(entry, twob_attr, None) or 0)
        if abs(twob_val - book_val) > float(VALUE_TOLERANCE):
            details[field_name] = {"books": book_val, "2b": twob_val}

    return details
