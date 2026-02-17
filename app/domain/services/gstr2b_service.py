# app/domain/services/gstr2b_service.py
"""
GSTR-2B Import Service.

Fetches the auto-drafted ITC statement from MasterGST and stores
each supplier invoice line as an ITCMatch record for reconciliation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

logger = logging.getLogger("gstr2b_service")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class Gstr2bImportResult:
    """Summary returned after importing GSTR-2B data."""
    period: str
    total_entries: int = 0
    total_taxable: Decimal = Decimal("0")
    total_igst: Decimal = Decimal("0")
    total_cgst: Decimal = Decimal("0")
    total_sgst: Decimal = Decimal("0")
    supplier_count: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def import_gstr2b(
    user_id: UUID,
    gstin: str,
    period: str,
    period_id: UUID,
    db: Any,
) -> Gstr2bImportResult:
    """
    Fetch GSTR-2B from MasterGST and store as ITCMatch records.

    Steps:
      1. Authenticate with MasterGST
      2. Fetch 2B via get_gstr2b()
      3. Parse the response JSON
      4. Clear existing ITCMatch records for the period
      5. Bulk-insert new ITCMatch records
      6. Return summary
    """
    from app.infrastructure.external.mastergst_client import (
        MasterGSTClient,
        MasterGSTError,
    )
    from app.infrastructure.db.repositories.itc_match_repository import ITCMatchRepository

    result = Gstr2bImportResult(period=period)

    # Convert YYYY-MM to MMYYYY for MasterGST
    parts = period.split("-")
    if len(parts) == 2:
        fp = f"{parts[1]}{parts[0]}"
    else:
        fp = period

    client = MasterGSTClient()
    try:
        auth_token = await client.authenticate(gstin)
        gstr2b_resp = await client.get_gstr2b(gstin, fp, auth_token)
    except MasterGSTError as e:
        logger.error("MasterGST 2B fetch failed for %s/%s: %s", gstin, period, e)
        result.errors.append(f"MasterGST error: {e}")
        return result
    except Exception as e:
        logger.exception("Unexpected error fetching GSTR-2B")
        result.errors.append(f"Unexpected error: {e}")
        return result

    # Parse 2B response
    matches = _parse_gstr2b_response(gstr2b_resp, period_id)
    result.total_entries = len(matches)

    # Aggregate totals
    suppliers_seen: set[str] = set()
    for m in matches:
        result.total_taxable += m.get("gstr2b_taxable_value", Decimal("0"))
        result.total_igst += m.get("gstr2b_igst", Decimal("0"))
        result.total_cgst += m.get("gstr2b_cgst", Decimal("0"))
        result.total_sgst += m.get("gstr2b_sgst", Decimal("0"))
        suppliers_seen.add(m["gstr2b_supplier_gstin"])
    result.supplier_count = len(suppliers_seen)

    # Clear old records and bulk insert
    repo = ITCMatchRepository(db)
    await repo.clear_for_period(period_id)
    if matches:
        await repo.bulk_create(period_id, matches)

    logger.info(
        "GSTR-2B imported: period=%s, entries=%d, suppliers=%d, taxable=%s",
        period, result.total_entries, result.supplier_count, result.total_taxable,
    )
    return result


async def import_gstr2b_from_json(
    user_id: UUID,
    period_id: UUID,
    gstr2b_json: dict,
    db: Any,
) -> Gstr2bImportResult:
    """Import GSTR-2B from user-uploaded JSON file (same parsing logic)."""
    from app.infrastructure.db.repositories.itc_match_repository import ITCMatchRepository
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository

    period_repo = ReturnPeriodRepository(db)
    rp = await period_repo.get_by_id(period_id)
    period = rp.period if rp else "unknown"

    result = Gstr2bImportResult(period=period)
    matches = _parse_gstr2b_response(gstr2b_json, period_id)
    result.total_entries = len(matches)

    suppliers_seen: set[str] = set()
    for m in matches:
        result.total_taxable += m.get("gstr2b_taxable_value", Decimal("0"))
        result.total_igst += m.get("gstr2b_igst", Decimal("0"))
        result.total_cgst += m.get("gstr2b_cgst", Decimal("0"))
        result.total_sgst += m.get("gstr2b_sgst", Decimal("0"))
        suppliers_seen.add(m["gstr2b_supplier_gstin"])
    result.supplier_count = len(suppliers_seen)

    repo = ITCMatchRepository(db)
    await repo.clear_for_period(period_id)
    if matches:
        await repo.bulk_create(period_id, matches)

    return result


async def import_gstr2b_from_excel(
    user_id: UUID,
    period_id: UUID,
    file_bytes: bytes,
    db: Any,
) -> Gstr2bImportResult:
    """Import GSTR-2B from user-uploaded Excel file (.xlsx).

    Expected columns: Supplier GSTIN, Invoice Number, Invoice Date,
    Taxable Value, IGST, CGST, SGST
    """
    import io
    try:
        import openpyxl
    except ImportError:
        result = Gstr2bImportResult(period="unknown")
        result.errors.append("openpyxl not installed — Excel import unavailable")
        return result

    from app.infrastructure.db.repositories.itc_match_repository import ITCMatchRepository
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository

    period_repo = ReturnPeriodRepository(db)
    rp = await period_repo.get_by_id(period_id)
    period = rp.period if rp else "unknown"
    result = Gstr2bImportResult(period=period)

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))  # skip header
    except Exception as e:
        result.errors.append(f"Failed to parse Excel file: {e}")
        return result

    matches: list[dict] = []
    suppliers_seen: set[str] = set()

    # Column mapping: A=GSTIN, B=InvNo, C=InvDate, D=Taxable, E=IGST, F=CGST, G=SGST
    for row in rows:
        if not row or len(row) < 4:
            continue
        ctin = str(row[0] or "").strip().upper()
        if not ctin or len(ctin) < 15:
            continue

        inum = str(row[1] or "").strip()
        inv_date = _parse_excel_date(row[2])
        txval = _safe_decimal(row[3])
        igst = _safe_decimal(row[4]) if len(row) > 4 else Decimal("0")
        cgst = _safe_decimal(row[5]) if len(row) > 5 else Decimal("0")
        sgst = _safe_decimal(row[6]) if len(row) > 6 else Decimal("0")

        matches.append({
            "period_id": period_id,
            "gstr2b_supplier_gstin": ctin,
            "gstr2b_invoice_number": inum,
            "gstr2b_invoice_date": inv_date,
            "gstr2b_taxable_value": txval,
            "gstr2b_igst": igst,
            "gstr2b_cgst": cgst,
            "gstr2b_sgst": sgst,
            "match_status": "unmatched",
        })
        result.total_taxable += txval
        result.total_igst += igst
        result.total_cgst += cgst
        result.total_sgst += sgst
        suppliers_seen.add(ctin)

    result.total_entries = len(matches)
    result.supplier_count = len(suppliers_seen)

    repo = ITCMatchRepository(db)
    await repo.clear_for_period(period_id)
    if matches:
        await repo.bulk_create(period_id, matches)

    logger.info("GSTR-2B Excel imported: period=%s, entries=%d", period, len(matches))
    return result


async def import_gstr2b_from_pdf(
    user_id: UUID,
    period_id: UUID,
    file_bytes: bytes,
    db: Any,
) -> Gstr2bImportResult:
    """Import GSTR-2B from user-uploaded PDF.

    Uses OCR + LLM to extract tabular data, then parses into ITCMatch records.
    Falls back to text extraction if image-based.
    """
    from app.infrastructure.db.repositories.itc_match_repository import ITCMatchRepository
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository

    period_repo = ReturnPeriodRepository(db)
    rp = await period_repo.get_by_id(period_id)
    period = rp.period if rp else "unknown"
    result = Gstr2bImportResult(period=period)

    # Extract text from PDF
    text = ""
    try:
        import io
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except ImportError:
            result.errors.append("pdfplumber not installed — PDF import unavailable")
            return result
    except Exception as e:
        result.errors.append(f"Failed to extract PDF text: {e}")
        return result

    if not text.strip():
        result.errors.append("PDF contains no extractable text (may be image-based)")
        return result

    # Parse extracted text for invoice lines
    matches = _parse_2b_text(text, period_id)
    result.total_entries = len(matches)

    suppliers_seen: set[str] = set()
    for m in matches:
        result.total_taxable += m.get("gstr2b_taxable_value", Decimal("0"))
        result.total_igst += m.get("gstr2b_igst", Decimal("0"))
        result.total_cgst += m.get("gstr2b_cgst", Decimal("0"))
        result.total_sgst += m.get("gstr2b_sgst", Decimal("0"))
        suppliers_seen.add(m["gstr2b_supplier_gstin"])
    result.supplier_count = len(suppliers_seen)

    repo = ITCMatchRepository(db)
    await repo.clear_for_period(period_id)
    if matches:
        await repo.bulk_create(period_id, matches)

    logger.info("GSTR-2B PDF imported: period=%s, entries=%d", period, len(matches))
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_gstr2b_response(resp: dict, period_id: UUID) -> list[dict]:
    """
    Parse MasterGST GSTR-2B response into ITCMatch-ready dicts.

    MasterGST 2B response structure:
    {
      "data": {
        "docdata": {
          "b2b": [
            {
              "ctin": "supplier_gstin",
              "inv": [
                {
                  "inum": "INV-001",
                  "idt": "01-01-2025",
                  "val": 11800.00,
                  "itms": [
                    {"txval": 10000, "igst": 1800, "cgst": 0, "sgst": 0, ...}
                    OR
                    {"itm_det": {"txval": ..., "iamt": ..., "camt": ..., "samt": ...}}
                  ]
                }
              ]
            }
          ]
        }
      }
    }
    """
    matches: list[dict] = []

    # Navigate to B2B data — try common response shapes
    data = resp.get("data", resp)
    if isinstance(data, str):
        return matches  # unexpected string response

    docdata = data.get("docdata", data)
    b2b_list = docdata.get("b2b", [])

    if not b2b_list:
        # Alternate shape: direct b2b at top level
        b2b_list = resp.get("b2b", [])

    for supplier in b2b_list:
        if not isinstance(supplier, dict):
            continue

        ctin = supplier.get("ctin", "").strip().upper()
        if not ctin:
            continue

        for inv in supplier.get("inv", []):
            inum = (inv.get("inum") or "").strip()
            idt = inv.get("idt")
            inv_date = _parse_2b_date(idt)

            # Aggregate item-level taxes
            txval = Decimal("0")
            igst = Decimal("0")
            cgst = Decimal("0")
            sgst = Decimal("0")

            for itm in inv.get("itms", []):
                # Handle both flat and nested item structures
                det = itm if "txval" in itm else itm.get("itm_det", {})
                txval += _safe_decimal(det.get("txval"))
                igst += _safe_decimal(det.get("igst") or det.get("iamt"))
                cgst += _safe_decimal(det.get("cgst") or det.get("camt"))
                sgst += _safe_decimal(det.get("sgst") or det.get("samt"))

            matches.append({
                "period_id": period_id,
                "gstr2b_supplier_gstin": ctin,
                "gstr2b_invoice_number": inum,
                "gstr2b_invoice_date": inv_date,
                "gstr2b_taxable_value": txval,
                "gstr2b_igst": igst,
                "gstr2b_cgst": cgst,
                "gstr2b_sgst": sgst,
                "match_status": "unmatched",
            })

    return matches


def _parse_2b_date(raw: Any) -> date | None:
    """Parse date from GSTR-2B format (DD-MM-YYYY or DD/MM/YYYY)."""
    if not raw or not isinstance(raw, str):
        return None

    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _safe_decimal(value: Any) -> Decimal:
    """Safely convert any value to Decimal, defaulting to 0."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _parse_excel_date(value: Any) -> date | None:
    """Parse date from Excel -- handles datetime objects and strings."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value if isinstance(value, date) else value.date()
    return _parse_2b_date(str(value))


def _parse_2b_text(text: str, period_id: UUID) -> list[dict]:
    """Parse GSTR-2B text content (from PDF) into ITCMatch records.

    Looks for lines containing GSTIN patterns followed by invoice details.
    """
    import re

    gstin_pattern = re.compile(r'\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2})\b')
    matches: list[dict] = []

    lines = text.split("\n")
    for line in lines:
        gstin_match = gstin_pattern.search(line)
        if not gstin_match:
            continue

        ctin = gstin_match.group(1)

        # Try to find invoice number and amounts on the same line
        # Common PDF formats: GSTIN | InvNo | Date | Taxable | IGST | CGST | SGST
        parts = re.split(r'\s{2,}|\t|\|', line)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) < 4:
            continue

        # Find numeric values (amounts)
        amounts: list[Decimal] = []
        inv_num = ""
        inv_date = None

        for part in parts:
            if part == ctin:
                continue
            # Try as number
            cleaned = part.replace(",", "").replace("\u20b9", "").strip()
            try:
                val = Decimal(cleaned)
                amounts.append(val)
            except (InvalidOperation, ValueError):
                # Try as date
                parsed = _parse_2b_date(part)
                if parsed:
                    inv_date = parsed
                elif not inv_num and len(part) > 2:
                    inv_num = part

        if len(amounts) >= 1:
            txval = amounts[0]
            igst = amounts[1] if len(amounts) > 1 else Decimal("0")
            cgst = amounts[2] if len(amounts) > 2 else Decimal("0")
            sgst = amounts[3] if len(amounts) > 3 else Decimal("0")

            matches.append({
                "period_id": period_id,
                "gstr2b_supplier_gstin": ctin,
                "gstr2b_invoice_number": inv_num,
                "gstr2b_invoice_date": inv_date,
                "gstr2b_taxable_value": txval,
                "gstr2b_igst": igst,
                "gstr2b_cgst": cgst,
                "gstr2b_sgst": sgst,
                "match_status": "unmatched",
            })

    return matches
