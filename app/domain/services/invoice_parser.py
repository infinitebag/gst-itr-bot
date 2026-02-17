# app/domain/services/invoice_parser.py

import re
from dataclasses import dataclass
from datetime import datetime

from app.domain.services.gstin_pan_validation import is_valid_gstin

GSTIN_REGEX = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")

# Expanded date patterns
DATE_REGEXES = [
    # dd-mm-yyyy or dd/mm/yyyy
    re.compile(
        r"\b(0?[1-9]|[12][0-9]|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20[0-9]{2})\b"
    ),
    # yyyy-mm-dd
    re.compile(
        r"\b(20[0-9]{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12][0-9]|3[01])\b"
    ),
    # dd-Mon-yyyy or dd-Mon-yy  (e.g. 20-May-25, 20-May-2025)
    re.compile(
        r"\b(0?[1-9]|[12][0-9]|3[01])[-/.\s]"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[-/.\s](\d{2,4})\b",
        re.IGNORECASE,
    ),
]

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

AMOUNT_REGEX = re.compile(
    r"₹?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"
)

# More specific amount extraction for labelled values
LABELLED_AMOUNT_RE = re.compile(
    r"[₹Rs.\s]*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*$"
)


@dataclass
class ParsedInvoice:
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
    tax_rate: float | None = None
    hsn_code: str | None = None
    item_description: str | None = None
    recipient_gstin: str | None = None

    supplier_gstin_valid: bool | None = None
    receiver_gstin_valid: bool | None = None


def _parse_amount(s: str) -> float | None:
    s = s.replace("₹", "").replace("Rs", "").replace("rs", "")
    s = s.replace(" ", "").replace(",", "")
    # Handle negative amounts like (-)0.44
    s = re.sub(r"\([-−]\)", "-", s)
    try:
        return float(s)
    except Exception:
        return None


def _extract_amount_from_line(line: str, keyword: str) -> float | None:
    """Extract the amount that appears after a keyword on a line."""
    lower = line.lower()
    idx = lower.find(keyword.lower())
    if idx == -1:
        return None

    after = line[idx + len(keyword):]
    # Find all amounts in the portion after the keyword
    amounts = AMOUNT_REGEX.findall(after)
    if amounts:
        # Return the last amount (usually the value, not the rate %)
        return _parse_amount(amounts[-1])
    return None


def _find_gstin_with_context(lines: list[str], ocr_text: str) -> tuple[str | None, str | None]:
    """
    Find supplier and receiver GSTINs using contextual clues.
    Looks for keywords near GSTINs to determine which is which.
    """
    supplier_gstin = None
    receiver_gstin = None

    supplier_keywords = {"supplier", "seller", "from", "consignor", "shipped from"}
    receiver_keywords = {
        "receiver", "buyer", "bill to", "ship to", "consignee",
        "shipped to", "buyer (bill to)",
    }

    all_gstins = GSTIN_REGEX.findall(ocr_text)
    unique_gstins = list(dict.fromkeys(all_gstins))  # preserve order, dedupe

    if not unique_gstins:
        return None, None

    # Try contextual matching first
    for i, line in enumerate(lines):
        lower = line.lower()
        context = lower
        # Also check surrounding lines (±2) for context
        for offset in range(1, 3):
            if i - offset >= 0:
                context += " " + lines[i - offset].lower()
            if i + offset < len(lines):
                context += " " + lines[i + offset].lower()

        gstins_in_line = GSTIN_REGEX.findall(line)
        for gstin in gstins_in_line:
            if any(kw in context for kw in receiver_keywords) and not receiver_gstin:
                receiver_gstin = gstin
            elif any(kw in context for kw in supplier_keywords) and not supplier_gstin:
                supplier_gstin = gstin

    # Fallback: first unique GSTIN = supplier, second = receiver
    if not supplier_gstin and unique_gstins:
        supplier_gstin = unique_gstins[0]
    if not receiver_gstin and len(unique_gstins) > 1:
        # Pick the first one that's different from supplier
        for g in unique_gstins:
            if g != supplier_gstin:
                receiver_gstin = g
                break

    return supplier_gstin, receiver_gstin


def _parse_date_text(text: str) -> datetime | None:
    """Parse a date string trying multiple formats."""
    for regex in DATE_REGEXES:
        m = regex.search(text)
        if not m:
            continue
        try:
            groups = m.groups()
            if regex is DATE_REGEXES[0]:
                # dd-mm-yyyy
                dd, mm, yyyy = groups
                return datetime(int(yyyy), int(mm), int(dd))
            elif regex is DATE_REGEXES[1]:
                # yyyy-mm-dd
                yyyy, mm, dd = groups
                return datetime(int(yyyy), int(mm), int(dd))
            elif regex is DATE_REGEXES[2]:
                # dd-Mon-yy or dd-Mon-yyyy
                dd, mon_name, yr = groups
                mm = MONTH_NAMES.get(mon_name.lower()[:3], 0)
                if mm == 0:
                    continue
                yr_int = int(yr)
                if yr_int < 100:
                    yr_int += 2000
                return datetime(yr_int, mm, int(dd))
        except (ValueError, TypeError):
            continue
    return None


def parse_invoice_text(ocr_text: str) -> ParsedInvoice:
    """
    Heuristic parser: best-effort extraction from messy OCR text.
    Improved to handle diverse Indian invoice formats.
    """
    parsed = ParsedInvoice()
    if not ocr_text:
        return parsed

    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]

    # --- GSTINs (context-aware) ---
    parsed.supplier_gstin, parsed.receiver_gstin = _find_gstin_with_context(
        lines, ocr_text
    )

    # --- Invoice number ---
    inv_num_patterns = [
        r"invoice\s*(?:no\.?|number|#)\s*[:.\s]\s*(.+)",
        r"inv\s*(?:no\.?|#)\s*[:.\s]\s*(.+)",
        r"bill\s*(?:no\.?|number)\s*[:.\s]\s*(.+)",
        r"invoice\s+no\s*\.?\s*\n\s*(.+)",  # "Invoice No." on one line, value on next
    ]
    for line in lines:
        lowered = line.lower()
        for pat in inv_num_patterns:
            m = re.search(pat, lowered)
            if m:
                candidate = m.group(1).strip()
                # Clean: keep alphanumeric, slashes, dashes
                candidate = re.sub(r"[^A-Za-z0-9/\-]", "", candidate)
                if candidate:
                    parsed.invoice_number = candidate[:50]
                    break
        if parsed.invoice_number:
            break

    # If "Invoice No." label found on one line and value might be a nearby field
    if not parsed.invoice_number:
        for i, line in enumerate(lines):
            if re.search(r"invoice\s*no\.?", line, re.IGNORECASE):
                # Check if there's a value on the same line after a tab/multiple spaces
                parts = re.split(r"\s{2,}|\t", line)
                for part in parts[1:]:
                    candidate = re.sub(r"[^A-Za-z0-9/\-]", "", part.strip())
                    if candidate and len(candidate) <= 50:
                        parsed.invoice_number = candidate
                        break
                # Also check next line
                if not parsed.invoice_number and i + 1 < len(lines):
                    candidate = re.sub(r"[^A-Za-z0-9/\-]", "", lines[i + 1].strip())
                    if candidate and len(candidate) <= 20:
                        parsed.invoice_number = candidate
                break

    # --- Date ---
    # Try lines near "date", "invoice date", "dated" keywords first
    date_lines = []
    other_lines = []
    for line in lines:
        lower = line.lower()
        if "date" in lower or "dated" in lower:
            date_lines.append(line)
        else:
            other_lines.append(line)

    for line in date_lines + other_lines:
        dt = _parse_date_text(line)
        if dt:
            parsed.invoice_date = dt
            break

    # --- HSN/SAC Code ---
    for line in lines:
        m = re.search(r"\b(HSN|SAC)\b[:/\s]*(\d{4,8})\b", line, re.IGNORECASE)
        if m:
            parsed.hsn_code = m.group(2)
            break
    # Also check for standalone 4-8 digit codes in HSN column context
    if not parsed.hsn_code:
        for line in lines:
            if re.search(r"hsn|sac", line, re.IGNORECASE):
                m = re.search(r"\b(\d{4,8})\b", line)
                if m:
                    parsed.hsn_code = m.group(1)
                    break

    # --- Tax Rate ---
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in ("gst rate", "tax rate", "rate of tax", "igst", "cgst")):
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
            if m:
                rate = float(m.group(1))
                # Total GST rate — if CGST, double for total; if already total, keep
                if "cgst" in lower or "sgst" in lower:
                    parsed.tax_rate = rate * 2
                else:
                    parsed.tax_rate = rate
                break

    # --- Amounts: CGST / SGST / IGST ---
    for line in lines:
        lower = line.lower()
        amounts_in_line = AMOUNT_REGEX.findall(line)
        if not amounts_in_line:
            continue

        if "cgst" in lower and parsed.cgst_amount is None:
            # Pick the last numeric amount (skip rate percentages)
            for amt_str in reversed(amounts_in_line):
                val = _parse_amount(amt_str)
                if val is not None and val > 1:  # skip percentage-like values
                    parsed.cgst_amount = val
                    break
            if parsed.cgst_amount is None:
                parsed.cgst_amount = _parse_amount(amounts_in_line[-1])

        elif "sgst" in lower and parsed.sgst_amount is None:
            for amt_str in reversed(amounts_in_line):
                val = _parse_amount(amt_str)
                if val is not None and val > 1:
                    parsed.sgst_amount = val
                    break
            if parsed.sgst_amount is None:
                parsed.sgst_amount = _parse_amount(amounts_in_line[-1])

        elif "igst" in lower and ("igst" not in lower.split("gstin")[0] if "gstin" in lower else True):
            # Make sure "igst" isn't part of a GSTIN field label
            if parsed.igst_amount is None:
                for amt_str in reversed(amounts_in_line):
                    val = _parse_amount(amt_str)
                    if val is not None and val > 1:
                        parsed.igst_amount = val
                        break
                if parsed.igst_amount is None:
                    parsed.igst_amount = _parse_amount(amounts_in_line[-1])

    # --- Tax amount (sum of CGST/SGST/IGST if present) ---
    tax_parts = [
        x
        for x in [parsed.cgst_amount, parsed.sgst_amount, parsed.igst_amount]
        if x is not None
    ]
    if tax_parts:
        parsed.tax_amount = round(sum(tax_parts), 2)

    # If no individual tax components, look for "Total Tax" or "Tax Amount" line
    if parsed.tax_amount is None:
        for line in lines:
            lower = line.lower()
            if ("total tax" in lower or "tax amount" in lower) and "taxable" not in lower:
                m = AMOUNT_REGEX.search(line)
                if m:
                    parsed.tax_amount = _parse_amount(m.group(1))
                    break

    # --- Total / taxable values ---
    # Look for specific labels first, then fall back to generic "total"
    total_patterns = [
        (r"grand\s*total", True),
        (r"total\s*amount", True),
        (r"invoice\s*total", True),
        (r"net\s*amount", True),
        (r"amount\s*chargeable", True),
        (r"total\s*tax\s*amount", False),  # This is "Total Tax Amount" → tax, not total
        (r"\btotal\b", True),
    ]
    taxable_patterns = [
        r"taxable\s*value",
        r"taxable\s*amount",
        r"assessable\s*value",
        r"base\s*amount",
    ]

    # First try to find explicit taxable value
    for line in lines:
        lower = line.lower()
        for pat in taxable_patterns:
            if re.search(pat, lower):
                amounts = AMOUNT_REGEX.findall(line)
                if amounts:
                    val = _parse_amount(amounts[-1])
                    if val is not None and val > 0:
                        parsed.taxable_value = val
                        break
        if parsed.taxable_value is not None:
            break

    # Find total amount
    candidate_totals: list[float] = []
    for line in lines:
        lower = line.lower()
        for pat, is_total in total_patterns:
            if re.search(pat, lower):
                amounts = AMOUNT_REGEX.findall(line)
                if amounts:
                    val = _parse_amount(amounts[-1])
                    if val is not None and val > 0:
                        if is_total:
                            candidate_totals.append(val)
                        break

    if candidate_totals:
        # The largest amount is most likely the final invoice total
        parsed.total_amount = max(candidate_totals)

    # --- Derive missing values ---
    if parsed.total_amount is not None and parsed.tax_amount is not None:
        if parsed.taxable_value is None:
            parsed.taxable_value = round(max(parsed.total_amount - parsed.tax_amount, 0.0), 2)
    elif parsed.taxable_value is not None and parsed.tax_amount is not None:
        if parsed.total_amount is None:
            parsed.total_amount = round(parsed.taxable_value + parsed.tax_amount, 2)

    # --- Place of supply ---
    for line in lines:
        lower = line.lower()
        if "place of supply" in lower:
            parts = line.split(":", 1)
            if len(parts) > 1:
                parsed.place_of_supply = parts[1].strip()[:100]
            else:
                # Try text after "Place of Supply"
                m = re.search(r"place\s*of\s*supply\s*[:\-]?\s*(.+)", line, re.IGNORECASE)
                if m:
                    parsed.place_of_supply = m.group(1).strip()[:100]
            break

    # Fallback: look for "State Name" / "State" near receiver info
    if not parsed.place_of_supply:
        for i, line in enumerate(lines):
            lower = line.lower()
            if "state name" in lower or ("state" in lower and "code" in lower):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    val = parts[1].strip()
                    # Remove "Code : XX" suffix
                    val = re.sub(r",?\s*code\s*[:.\s]*\d+", "", val, flags=re.IGNORECASE).strip()
                    if val and len(val) < 50:
                        parsed.place_of_supply = val
                        break

    # --- Validate GSTINs ---
    if parsed.supplier_gstin:
        parsed.supplier_gstin_valid = is_valid_gstin(parsed.supplier_gstin)
    if parsed.receiver_gstin:
        parsed.receiver_gstin_valid = is_valid_gstin(parsed.receiver_gstin)

    return parsed
