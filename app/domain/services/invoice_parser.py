# app/domain/services/invoice_parser.py

import re
from dataclasses import dataclass
from datetime import datetime

from app.domain.services.gstin_pan_validation import is_valid_gstin

GSTIN_REGEX = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
DATE_REGEXES = [
    re.compile(
        r"\b(0[1-9]|[12][0-9]|3[01])[-/](0[1-9]|1[0-2])[-/](20[0-9]{2})\b"
    ),  # dd-mm-yyyy or dd/mm/yyyy
    re.compile(
        r"\b(20[0-9]{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12][0-9]|3[01])\b"
    ),  # yyyy-mm-dd
]
AMOUNT_REGEX = re.compile(
    r"₹?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"
)


@dataclass
class ParsedInvoice:
    def __init__(self):
        self.tax_rate = None
        self.recipient_gstin = None

    supplier_gstin: str | None = None
    receiver_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: datetime | None = None
    taxable_value: float | None = None
    total_amount: float | None = None
    tax_amount: float | None = None
    cgst_amount: float | None = None
    sgst_amount: float | None = None
    igst_amount: float | None = None
    place_of_supply: str | None = None

    supplier_gstin_valid: bool | None = None
    receiver_gstin_valid: bool | None = None


def _parse_amount(s: str) -> float | None:
    s = s.replace("₹", "").replace(" ", "")
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def parse_invoice_text(ocr_text: str) -> ParsedInvoice:
    """
    Heuristic parser: best-effort extraction from messy OCR text.
    Not perfect, but enough for a v1 to populate GSTR prototypes.
    """
    parsed = ParsedInvoice()
    if not ocr_text:
        return parsed

    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]

    # --- GSTINs ---
    gstins = GSTIN_REGEX.findall(ocr_text)
    if gstins:
        parsed.supplier_gstin = gstins[0]
        if len(gstins) > 1:
            parsed.receiver_gstin = gstins[1]

    # --- Invoice number ---
    for line in lines:
        lowered = line.lower()
        if "invoice no" in lowered or "inv no" in lowered or "invoice #" in lowered:
            # Take text after ':' or 'no'
            parts = re.split(r"[:#]", line, maxsplit=1)
            if len(parts) > 1:
                candidate = parts[1].strip()
            else:
                candidate = line
            candidate = re.sub(r"[^A-Za-z0-9/-]", "", candidate)
            if candidate:
                parsed.invoice_number = candidate[:50]
                break

    # --- Date ---
    for line in lines:
        for regex in DATE_REGEXES:
            m = regex.search(line)
            if not m:
                continue
            try:
                if regex is DATE_REGEXES[0]:
                    # dd-mm-yyyy
                    dd, mm, yyyy = m.groups()
                    parsed.invoice_date = datetime(int(yyyy), int(mm), int(dd))
                else:
                    # yyyy-mm-dd
                    yyyy, mm, dd = m.groups()
                    parsed.invoice_date = datetime(int(yyyy), int(mm), int(dd))
                break
            except Exception:
                continue
        if parsed.invoice_date:
            break

    # --- Amounts: CGST / SGST / IGST ---
    for line in lines:
        lower = line.lower()
        if "cgst" in lower:
            m = AMOUNT_REGEX.search(line)
            if m:
                parsed.cgst_amount = _parse_amount(m.group(1))
        elif "sgst" in lower:
            m = AMOUNT_REGEX.search(line)
            if m:
                parsed.sgst_amount = _parse_amount(m.group(1))
        elif "igst" in lower:
            m = AMOUNT_REGEX.search(line)
            if m:
                parsed.igst_amount = _parse_amount(m.group(1))

    # --- Tax amount (sum of CGST/SGST/IGST if present) ---
    tax_parts = [
        x
        for x in [parsed.cgst_amount, parsed.sgst_amount, parsed.igst_amount]
        if x is not None
    ]
    if tax_parts:
        parsed.tax_amount = sum(tax_parts)

    # --- Total / taxable values: look for lines with 'total' ---
    candidate_totals: list[float] = []
    for line in lines:
        lower = line.lower()
        if "total" in lower:
            m = AMOUNT_REGEX.search(line)
            if m:
                val = _parse_amount(m.group(1))
                if val is not None:
                    candidate_totals.append(val)

    if candidate_totals:
        # Heuristic: largest is invoice total
        parsed.total_amount = max(candidate_totals)

    # --- Taxable value: total - tax if both are present ---
    if parsed.total_amount is not None and parsed.tax_amount is not None:
        parsed.taxable_value = max(parsed.total_amount - parsed.tax_amount, 0.0)

    # --- Place of supply ---
    for line in lines:
        lower = line.lower()
        if "place of supply" in lower or "pos" in lower:
            parts = line.split(":", 1)
            if len(parts) > 1:
                parsed.place_of_supply = parts[1].strip()[:100]
            else:
                parsed.place_of_supply = line[:100]
            break

    # --- Validate GSTINs ---
    if parsed.supplier_gstin:
        parsed.supplier_gstin_valid = is_valid_gstin(parsed.supplier_gstin)
    if parsed.receiver_gstin:
        parsed.receiver_gstin_valid = is_valid_gstin(parsed.receiver_gstin)

    return parsed

    return parsed
