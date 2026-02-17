# app/domain/services/itr_form_parser.py
"""
ITR form document parser — dataclasses, merge logic, and formatters.

Parses structured data from Form 16, Form 26AS, and AIS (Annual Information
Statement), merges data from multiple documents, and converts to ITR inputs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.domain.services.itr_service import ITR1Input, ITR2Input, ITR4Input

logger = logging.getLogger("itr_form_parser")

D = lambda x: Decimal(str(x)) if x else Decimal("0")  # noqa: E731


# ---------------------------------------------------------------------------
# Parsed document dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ParsedForm16:
    """Structured data extracted from Form 16 (employer TDS certificate)."""
    employer_name: str | None = None
    employer_tan: str | None = None
    employee_pan: str | None = None
    assessment_year: str | None = None
    gross_salary: Decimal | None = None
    standard_deduction: Decimal | None = None
    house_property_income: Decimal | None = None
    section_80c: Decimal | None = None
    section_80d: Decimal | None = None
    section_80e: Decimal | None = None
    section_80g: Decimal | None = None
    section_80ccd_1b: Decimal | None = None
    section_80tta: Decimal | None = None
    other_deductions: Decimal | None = None
    total_tax_deducted: Decimal | None = None


@dataclass
class ParsedForm26AS:
    """Structured data extracted from Form 26AS (tax credit statement)."""
    pan: str | None = None
    assessment_year: str | None = None
    tds_entries: list[dict] = field(default_factory=list)
    total_tds: Decimal | None = None
    total_tcs: Decimal | None = None
    advance_tax_paid: Decimal | None = None
    self_assessment_tax: Decimal | None = None


@dataclass
class ParsedAIS:
    """Structured data extracted from AIS (Annual Information Statement)."""
    pan: str | None = None
    salary_income: Decimal | None = None
    interest_income: Decimal | None = None
    dividend_income: Decimal | None = None
    rental_income: Decimal | None = None
    business_turnover: Decimal | None = None
    tds_total: Decimal | None = None
    sft_transactions: list[dict] = field(default_factory=list)


@dataclass
class MergedITRData:
    """Merged data from all uploaded documents."""
    # Income
    salary_income: Decimal = Decimal("0")
    house_property_income: Decimal = Decimal("0")
    other_income: Decimal = Decimal("0")
    interest_income: Decimal = Decimal("0")
    dividend_income: Decimal = Decimal("0")
    business_turnover: Decimal = Decimal("0")
    # Capital gains (extracted from 26AS/AIS)
    stcg_equity: Decimal = Decimal("0")    # Short-term CG from equity u/s 111A
    ltcg_equity: Decimal = Decimal("0")    # Long-term CG from equity u/s 112A
    # Deductions
    standard_deduction: Decimal = Decimal("75000")
    section_80c: Decimal = Decimal("0")
    section_80d: Decimal = Decimal("0")
    section_80e: Decimal = Decimal("0")
    section_80g: Decimal = Decimal("0")
    section_80ccd_1b: Decimal = Decimal("0")
    section_80tta: Decimal = Decimal("0")
    other_deductions: Decimal = Decimal("0")
    # Tax paid
    tds_total: Decimal = Decimal("0")
    advance_tax: Decimal = Decimal("0")
    self_assessment_tax: Decimal = Decimal("0")
    # Metadata
    pan: str = ""
    assessment_year: str = "2025-26"
    sources: list[str] = field(default_factory=list)
    # Raw parsed data (for mismatch detection)
    raw_form16: dict | None = None
    raw_form26as: dict | None = None
    raw_ais: dict | None = None


# ---------------------------------------------------------------------------
# Merge functions
# ---------------------------------------------------------------------------

def merge_form16(merged: MergedITRData, f16: ParsedForm16) -> MergedITRData:
    """Merge Form 16 data into the combined ITR data.

    Strategy: For income, take the maximum of existing vs new. For deductions,
    prefer Form 16 values (employer-reported) over existing if larger.
    """
    if f16.employee_pan and not merged.pan:
        merged.pan = f16.employee_pan
    if f16.assessment_year and merged.assessment_year == "2025-26":
        merged.assessment_year = f16.assessment_year

    # Income — take maximum
    if f16.gross_salary is not None:
        merged.salary_income = max(merged.salary_income, f16.gross_salary)
    if f16.house_property_income is not None:
        # House property can be negative (loss), so use Form 16 if present
        merged.house_property_income = f16.house_property_income

    # Standard deduction from Form 16
    if f16.standard_deduction is not None:
        merged.standard_deduction = f16.standard_deduction

    # Deductions — take maximum (Form 16 is authoritative for employer-verified data)
    if f16.section_80c is not None:
        merged.section_80c = max(merged.section_80c, f16.section_80c)
    if f16.section_80d is not None:
        merged.section_80d = max(merged.section_80d, f16.section_80d)
    if f16.section_80e is not None:
        merged.section_80e = max(merged.section_80e, f16.section_80e)
    if f16.section_80g is not None:
        merged.section_80g = max(merged.section_80g, f16.section_80g)
    if f16.section_80ccd_1b is not None:
        merged.section_80ccd_1b = max(merged.section_80ccd_1b, f16.section_80ccd_1b)
    if f16.section_80tta is not None:
        merged.section_80tta = max(merged.section_80tta, f16.section_80tta)
    if f16.other_deductions is not None:
        merged.other_deductions = max(merged.other_deductions, f16.other_deductions)

    # TDS from employer
    if f16.total_tax_deducted is not None:
        merged.tds_total = max(merged.tds_total, f16.total_tax_deducted)

    if "form16" not in merged.sources:
        merged.sources.append("form16")

    # Store raw parsed data for mismatch detection
    merged.raw_form16 = _form16_to_raw(f16)

    return merged


def _form16_to_raw(f16: ParsedForm16) -> dict:
    """Convert ParsedForm16 to a raw dict for storage."""
    return {
        "gross_salary": str(f16.gross_salary) if f16.gross_salary is not None else None,
        "total_tax_deducted": str(f16.total_tax_deducted) if f16.total_tax_deducted is not None else None,
        "house_property_income": str(f16.house_property_income) if f16.house_property_income is not None else None,
        "section_80c": str(f16.section_80c) if f16.section_80c is not None else None,
        "section_80d": str(f16.section_80d) if f16.section_80d is not None else None,
        "employer_name": f16.employer_name,
        "employee_pan": f16.employee_pan,
        "assessment_year": f16.assessment_year,
    }


def merge_form26as(merged: MergedITRData, f26: ParsedForm26AS) -> MergedITRData:
    """Merge Form 26AS data into the combined ITR data.

    Strategy: 26AS is the most authoritative source for TDS, advance tax,
    and self-assessment tax. Its totals override existing values.
    """
    if f26.pan and not merged.pan:
        merged.pan = f26.pan
    if f26.assessment_year and merged.assessment_year == "2025-26":
        merged.assessment_year = f26.assessment_year

    # TDS — Form 26AS is authoritative, override
    if f26.total_tds is not None:
        merged.tds_total = f26.total_tds

    # Advance tax and self-assessment tax
    if f26.advance_tax_paid is not None:
        merged.advance_tax = f26.advance_tax_paid
    if f26.self_assessment_tax is not None:
        merged.self_assessment_tax = f26.self_assessment_tax

    if "26as" not in merged.sources:
        merged.sources.append("26as")

    # Store raw parsed data for mismatch detection
    merged.raw_form26as = _form26as_to_raw(f26)

    return merged


def _form26as_to_raw(f26: ParsedForm26AS) -> dict:
    """Convert ParsedForm26AS to a raw dict for storage."""
    return {
        "total_tds": str(f26.total_tds) if f26.total_tds is not None else None,
        "total_tcs": str(f26.total_tcs) if f26.total_tcs is not None else None,
        "advance_tax_paid": str(f26.advance_tax_paid) if f26.advance_tax_paid is not None else None,
        "self_assessment_tax": str(f26.self_assessment_tax) if f26.self_assessment_tax is not None else None,
        "pan": f26.pan,
        "assessment_year": f26.assessment_year,
        "tds_entries": f26.tds_entries,
    }


def merge_ais(merged: MergedITRData, ais: ParsedAIS) -> MergedITRData:
    """Merge AIS data into the combined ITR data.

    Strategy: AIS provides additional income sources not in Form 16 (interest,
    dividends, rental). For salary, take max of existing vs AIS.
    """
    if ais.pan and not merged.pan:
        merged.pan = ais.pan

    # Income — take maximum between AIS and existing
    if ais.salary_income is not None:
        merged.salary_income = max(merged.salary_income, ais.salary_income)
    if ais.interest_income is not None:
        merged.interest_income = max(merged.interest_income, ais.interest_income)
    if ais.dividend_income is not None:
        merged.dividend_income = max(merged.dividend_income, ais.dividend_income)
    if ais.rental_income is not None:
        merged.house_property_income = max(merged.house_property_income, ais.rental_income)
    if ais.business_turnover is not None:
        merged.business_turnover = max(merged.business_turnover, ais.business_turnover)

    # TDS from AIS — only use if no 26AS data (26AS is more authoritative)
    if ais.tds_total is not None and "26as" not in merged.sources:
        merged.tds_total = max(merged.tds_total, ais.tds_total)

    # Compute other_income from interest + dividend
    merged.other_income = merged.interest_income + merged.dividend_income

    if "ais" not in merged.sources:
        merged.sources.append("ais")

    # Store raw parsed data for mismatch detection
    merged.raw_ais = _ais_to_raw(ais)

    return merged


def _ais_to_raw(ais: ParsedAIS) -> dict:
    """Convert ParsedAIS to a raw dict for storage."""
    return {
        "salary_income": str(ais.salary_income) if ais.salary_income is not None else None,
        "interest_income": str(ais.interest_income) if ais.interest_income is not None else None,
        "dividend_income": str(ais.dividend_income) if ais.dividend_income is not None else None,
        "rental_income": str(ais.rental_income) if ais.rental_income is not None else None,
        "business_turnover": str(ais.business_turnover) if ais.business_turnover is not None else None,
        "tds_total": str(ais.tds_total) if ais.tds_total is not None else None,
        "pan": ais.pan,
        "sft_transactions": ais.sft_transactions,
    }


# ---------------------------------------------------------------------------
# Editable fields mapping (for review/edit flow)
# ---------------------------------------------------------------------------

# Maps field number (as string) -> (attribute_name, display_label)
ITR_DOC_EDITABLE_FIELDS: dict[str, tuple[str, str]] = {
    "1": ("salary_income", "Gross Salary"),
    "2": ("house_property_income", "House Property Income"),
    "3": ("interest_income", "Interest Income"),
    "4": ("dividend_income", "Dividend Income"),
    "5": ("business_turnover", "Business Turnover"),
    "6": ("section_80c", "Section 80C"),
    "7": ("section_80d", "Section 80D"),
    "8": ("section_80e", "Section 80E"),
    "9": ("section_80g", "Section 80G"),
    "10": ("section_80ccd_1b", "Section 80CCD(1B)"),
    "11": ("section_80tta", "Section 80TTA"),
    "12": ("other_deductions", "Other Deductions"),
    "13": ("tds_total", "Total TDS"),
    "14": ("advance_tax", "Advance Tax"),
    "15": ("self_assessment_tax", "Self-Assessment Tax"),
}


# ---------------------------------------------------------------------------
# Format review summary
# ---------------------------------------------------------------------------

def format_review_summary(merged: MergedITRData, lang: str = "en") -> str:
    """Format merged data as a WhatsApp-friendly review summary with numbered fields."""
    sources_str = ", ".join(s.upper() for s in merged.sources) if merged.sources else "None"

    lines = [
        "--- Extracted Tax Data ---",
        f"Sources: {sources_str}",
        f"PAN: {merged.pan or 'Not detected'}",
        f"AY: {merged.assessment_year}",
        "",
        "INCOME:",
        f"  1. Gross Salary: Rs {float(merged.salary_income):,.0f}",
        f"  2. House Property: Rs {float(merged.house_property_income):,.0f}",
        f"  3. Interest Income: Rs {float(merged.interest_income):,.0f}",
        f"  4. Dividend Income: Rs {float(merged.dividend_income):,.0f}",
        f"  5. Business Turnover: Rs {float(merged.business_turnover):,.0f}",
        "",
        "DEDUCTIONS (Old Regime):",
        f"  6. Sec 80C: Rs {float(merged.section_80c):,.0f}",
        f"  7. Sec 80D: Rs {float(merged.section_80d):,.0f}",
        f"  8. Sec 80E: Rs {float(merged.section_80e):,.0f}",
        f"  9. Sec 80G: Rs {float(merged.section_80g):,.0f}",
        f"  10. Sec 80CCD(1B): Rs {float(merged.section_80ccd_1b):,.0f}",
        f"  11. Sec 80TTA: Rs {float(merged.section_80tta):,.0f}",
        f"  12. Other: Rs {float(merged.other_deductions):,.0f}",
        "",
        "TAX PAID:",
        f"  13. TDS: Rs {float(merged.tds_total):,.0f}",
        f"  14. Advance Tax: Rs {float(merged.advance_tax):,.0f}",
        f"  15. Self-Assessment: Rs {float(merged.self_assessment_tax):,.0f}",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Converters to ITR input dataclasses
# ---------------------------------------------------------------------------

def merged_to_itr1_input(merged: MergedITRData) -> ITR1Input:
    """Convert merged document data to ITR1Input for computation."""
    return ITR1Input(
        pan=merged.pan,
        assessment_year=merged.assessment_year,
        salary_income=merged.salary_income,
        standard_deduction=merged.standard_deduction,
        house_property_income=merged.house_property_income,
        other_income=merged.other_income + merged.interest_income + merged.dividend_income,
        section_80c=merged.section_80c,
        section_80d=merged.section_80d,
        section_80e=merged.section_80e,
        section_80g=merged.section_80g,
        section_80tta=merged.section_80tta,
        section_80ccd_1b=merged.section_80ccd_1b,
        other_deductions=merged.other_deductions,
        tds_total=merged.tds_total,
        advance_tax=merged.advance_tax,
        self_assessment_tax=merged.self_assessment_tax,
    )


def merged_to_itr4_input(merged: MergedITRData) -> ITR4Input:
    """Convert merged document data to ITR4Input for computation."""
    return ITR4Input(
        pan=merged.pan,
        assessment_year=merged.assessment_year,
        gross_turnover=merged.business_turnover,
        presumptive_rate=Decimal("8"),  # Default 8% for business
        salary_income=merged.salary_income,
        house_property_income=merged.house_property_income,
        other_income=merged.other_income + merged.interest_income + merged.dividend_income,
        section_80c=merged.section_80c,
        section_80d=merged.section_80d,
        other_deductions=merged.other_deductions,
        tds_total=merged.tds_total,
        advance_tax=merged.advance_tax,
    )


def merged_to_itr2_input(merged: MergedITRData) -> ITR2Input:
    """Convert merged document data to ITR2Input for computation."""
    return ITR2Input(
        pan=merged.pan,
        assessment_year=merged.assessment_year,
        salary_income=merged.salary_income,
        standard_deduction=merged.standard_deduction,
        house_property_income=merged.house_property_income,
        other_income=merged.other_income + merged.interest_income + merged.dividend_income,
        stcg_111a=merged.stcg_equity,
        ltcg_112a=merged.ltcg_equity,
        section_80c=merged.section_80c,
        section_80d=merged.section_80d,
        section_80e=merged.section_80e,
        section_80g=merged.section_80g,
        section_80tta=merged.section_80tta,
        section_80ccd_1b=merged.section_80ccd_1b,
        other_deductions=merged.other_deductions,
        tds_total=merged.tds_total,
        advance_tax=merged.advance_tax,
        self_assessment_tax=merged.self_assessment_tax,
    )


# ---------------------------------------------------------------------------
# Serialization helpers (for Redis session storage)
# ---------------------------------------------------------------------------

def merged_to_dict(merged: MergedITRData) -> dict:
    """Serialize MergedITRData to a JSON-safe dict for session storage."""
    return {
        "salary_income": str(merged.salary_income),
        "house_property_income": str(merged.house_property_income),
        "other_income": str(merged.other_income),
        "interest_income": str(merged.interest_income),
        "dividend_income": str(merged.dividend_income),
        "business_turnover": str(merged.business_turnover),
        "stcg_equity": str(merged.stcg_equity),
        "ltcg_equity": str(merged.ltcg_equity),
        "standard_deduction": str(merged.standard_deduction),
        "section_80c": str(merged.section_80c),
        "section_80d": str(merged.section_80d),
        "section_80e": str(merged.section_80e),
        "section_80g": str(merged.section_80g),
        "section_80ccd_1b": str(merged.section_80ccd_1b),
        "section_80tta": str(merged.section_80tta),
        "other_deductions": str(merged.other_deductions),
        "tds_total": str(merged.tds_total),
        "advance_tax": str(merged.advance_tax),
        "self_assessment_tax": str(merged.self_assessment_tax),
        "pan": merged.pan,
        "assessment_year": merged.assessment_year,
        "sources": merged.sources,
        "raw_form16": merged.raw_form16,
        "raw_form26as": merged.raw_form26as,
        "raw_ais": merged.raw_ais,
    }


def dict_to_merged(data: dict) -> MergedITRData:
    """Deserialize a dict from session storage back to MergedITRData."""
    if not data:
        return MergedITRData()
    return MergedITRData(
        salary_income=D(data.get("salary_income", 0)),
        house_property_income=D(data.get("house_property_income", 0)),
        other_income=D(data.get("other_income", 0)),
        interest_income=D(data.get("interest_income", 0)),
        dividend_income=D(data.get("dividend_income", 0)),
        business_turnover=D(data.get("business_turnover", 0)),
        stcg_equity=D(data.get("stcg_equity", 0)),
        ltcg_equity=D(data.get("ltcg_equity", 0)),
        standard_deduction=D(data.get("standard_deduction", 75000)),
        section_80c=D(data.get("section_80c", 0)),
        section_80d=D(data.get("section_80d", 0)),
        section_80e=D(data.get("section_80e", 0)),
        section_80g=D(data.get("section_80g", 0)),
        section_80ccd_1b=D(data.get("section_80ccd_1b", 0)),
        section_80tta=D(data.get("section_80tta", 0)),
        other_deductions=D(data.get("other_deductions", 0)),
        tds_total=D(data.get("tds_total", 0)),
        advance_tax=D(data.get("advance_tax", 0)),
        self_assessment_tax=D(data.get("self_assessment_tax", 0)),
        pan=data.get("pan", ""),
        assessment_year=data.get("assessment_year", "2025-26"),
        sources=list(data.get("sources", [])),
        raw_form16=data.get("raw_form16"),
        raw_form26as=data.get("raw_form26as"),
        raw_ais=data.get("raw_ais"),
    )


# ---------------------------------------------------------------------------
# Dict-to-dataclass converters (from LLM/Vision JSON output)
# ---------------------------------------------------------------------------

def dict_to_parsed_form16(data: dict) -> ParsedForm16:
    """Convert a dict (from LLM output) to ParsedForm16."""
    def _dec(val) -> Decimal | None:
        if val is None:
            return None
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError):
            return None

    return ParsedForm16(
        employer_name=data.get("employer_name"),
        employer_tan=data.get("employer_tan"),
        employee_pan=data.get("employee_pan"),
        assessment_year=data.get("assessment_year"),
        gross_salary=_dec(data.get("gross_salary")),
        standard_deduction=_dec(data.get("standard_deduction")),
        house_property_income=_dec(data.get("house_property_income")),
        section_80c=_dec(data.get("section_80c")),
        section_80d=_dec(data.get("section_80d")),
        section_80e=_dec(data.get("section_80e")),
        section_80g=_dec(data.get("section_80g")),
        section_80ccd_1b=_dec(data.get("section_80ccd_1b")),
        section_80tta=_dec(data.get("section_80tta")),
        other_deductions=_dec(data.get("other_deductions")),
        total_tax_deducted=_dec(data.get("total_tax_deducted")),
    )


def dict_to_parsed_form26as(data: dict) -> ParsedForm26AS:
    """Convert a dict (from LLM output) to ParsedForm26AS."""
    def _dec(val) -> Decimal | None:
        if val is None:
            return None
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError):
            return None

    return ParsedForm26AS(
        pan=data.get("pan"),
        assessment_year=data.get("assessment_year"),
        tds_entries=data.get("tds_entries") or [],
        total_tds=_dec(data.get("total_tds")),
        total_tcs=_dec(data.get("total_tcs")),
        advance_tax_paid=_dec(data.get("advance_tax_paid")),
        self_assessment_tax=_dec(data.get("self_assessment_tax")),
    )


def dict_to_parsed_ais(data: dict) -> ParsedAIS:
    """Convert a dict (from LLM output) to ParsedAIS."""
    def _dec(val) -> Decimal | None:
        if val is None:
            return None
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError):
            return None

    return ParsedAIS(
        pan=data.get("pan"),
        salary_income=_dec(data.get("salary_income")),
        interest_income=_dec(data.get("interest_income")),
        dividend_income=_dec(data.get("dividend_income")),
        rental_income=_dec(data.get("rental_income")),
        business_turnover=_dec(data.get("business_turnover")),
        tds_total=_dec(data.get("tds_total")),
        sft_transactions=data.get("sft_transactions") or [],
    )
