# app/domain/services/mismatch_detection.py
"""
AIS / 26AS / Form 16 / GST Mismatch Detection Engine.

Compares parsed income-tax documents and flags discrepancies such as TDS
mismatches, unreported income, high-value SFT transactions, and
GST-vs-ITR turnover differences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.services.itr_form_parser import (
    ParsedAIS,
    ParsedForm16,
    ParsedForm26AS,
)

logger = logging.getLogger("mismatch_detection")

D = lambda x: Decimal(str(x)) if x else Decimal("0")  # noqa: E731

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

TDS_WARNING_THRESHOLD = Decimal("500")
TDS_CRITICAL_THRESHOLD = Decimal("5000")
SALARY_DIFF_PCT = Decimal("5")         # percent
TURNOVER_DIFF_PCT = Decimal("10")      # percent
SFT_HIGH_VALUE = Decimal("1000000")    # Rs 10 lakh


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Mismatch:
    """A single discrepancy detected across documents."""
    field: str                # e.g. "tds_total", "salary_income"
    source_a: str             # e.g. "form16", "26as", "ais", "gst_invoices"
    source_b: str
    value_a: Decimal
    value_b: Decimal
    difference: Decimal       # absolute difference
    severity: str             # "warning" | "critical"
    suggested_action: str     # human-readable advice
    category: str             # "tds" | "income" | "sft" | "gst_turnover"


@dataclass
class MismatchReport:
    """Aggregated mismatch report across all uploaded documents."""
    mismatches: list[Mismatch] = field(default_factory=list)
    total_warnings: int = 0
    total_critical: int = 0
    documents_compared: list[str] = field(default_factory=list)
    has_gst_comparison: bool = False


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _compare_tds(
    form16: ParsedForm16,
    form26as: ParsedForm26AS,
) -> list[Mismatch]:
    """Compare TDS between Form 16 and Form 26AS."""
    results: list[Mismatch] = []
    f16_tds = D(form16.total_tax_deducted)
    f26_tds = D(form26as.total_tds)

    if f16_tds == 0 and f26_tds == 0:
        return results

    diff = abs(f16_tds - f26_tds)
    if diff > TDS_CRITICAL_THRESHOLD:
        results.append(Mismatch(
            field="tds_total",
            source_a="form16",
            source_b="26as",
            value_a=f16_tds,
            value_b=f26_tds,
            difference=diff,
            severity="critical",
            suggested_action=(
                "TDS amounts differ significantly. "
                "Form 26AS is the authoritative source — "
                "verify with your employer and check for missing TDS entries."
            ),
            category="tds",
        ))
    elif diff > TDS_WARNING_THRESHOLD:
        results.append(Mismatch(
            field="tds_total",
            source_a="form16",
            source_b="26as",
            value_a=f16_tds,
            value_b=f26_tds,
            difference=diff,
            severity="warning",
            suggested_action=(
                "Minor TDS difference detected. "
                "This may be due to timing of TDS deposits. "
                "Use the Form 26AS value for filing."
            ),
            category="tds",
        ))
    return results


def _compare_salary(
    form16: ParsedForm16,
    ais: ParsedAIS,
) -> list[Mismatch]:
    """Compare salary income between Form 16 and AIS."""
    results: list[Mismatch] = []
    f16_salary = D(form16.gross_salary)
    ais_salary = D(ais.salary_income)

    if f16_salary == 0 and ais_salary == 0:
        return results

    diff = abs(f16_salary - ais_salary)
    base = max(f16_salary, ais_salary)
    if base > 0:
        pct = (diff / base) * 100
        if pct > SALARY_DIFF_PCT:
            results.append(Mismatch(
                field="salary_income",
                source_a="form16",
                source_b="ais",
                value_a=f16_salary,
                value_b=ais_salary,
                difference=diff,
                severity="warning",
                suggested_action=(
                    f"Salary differs by {float(pct):.1f}%. "
                    "If you have multiple employers, ensure all Form 16s are uploaded. "
                    "The higher value should be declared."
                ),
                category="income",
            ))
    return results


def _compare_income_sources(
    form16: ParsedForm16,
    ais: ParsedAIS,
) -> list[Mismatch]:
    """Detect unreported income in AIS that is not in Form 16."""
    results: list[Mismatch] = []

    # Interest income — AIS may report bank interest not in Form 16
    ais_interest = D(ais.interest_income)
    if ais_interest > 0:
        results.append(Mismatch(
            field="interest_income",
            source_a="form16",
            source_b="ais",
            value_a=Decimal("0"),
            value_b=ais_interest,
            difference=ais_interest,
            severity="critical",
            suggested_action=(
                f"AIS reports interest income of Rs {float(ais_interest):,.0f} "
                "not in Form 16. This must be declared under 'Income from Other Sources'."
            ),
            category="income",
        ))

    # Dividend income
    ais_dividend = D(ais.dividend_income)
    if ais_dividend > 0:
        results.append(Mismatch(
            field="dividend_income",
            source_a="form16",
            source_b="ais",
            value_a=Decimal("0"),
            value_b=ais_dividend,
            difference=ais_dividend,
            severity="critical",
            suggested_action=(
                f"AIS reports dividend income of Rs {float(ais_dividend):,.0f}. "
                "This must be declared under 'Income from Other Sources'."
            ),
            category="income",
        ))

    # Rental income
    ais_rental = D(ais.rental_income)
    if ais_rental > 0:
        results.append(Mismatch(
            field="rental_income",
            source_a="form16",
            source_b="ais",
            value_a=Decimal("0"),
            value_b=ais_rental,
            difference=ais_rental,
            severity="critical",
            suggested_action=(
                f"AIS reports rental income of Rs {float(ais_rental):,.0f}. "
                "This must be declared under 'Income from House Property'."
            ),
            category="income",
        ))

    return results


def _compare_sft(ais: ParsedAIS) -> list[Mismatch]:
    """Flag high-value SFT (Specified Financial Transactions) from AIS."""
    results: list[Mismatch] = []

    for txn in (ais.sft_transactions or []):
        amount = D(txn.get("amount", 0))
        if amount >= SFT_HIGH_VALUE:
            desc = txn.get("description", txn.get("type", "High-value transaction"))
            results.append(Mismatch(
                field="sft_transaction",
                source_a="ais",
                source_b="ais",
                value_a=amount,
                value_b=Decimal("0"),
                difference=amount,
                severity="critical",
                suggested_action=(
                    f"High-value SFT detected: {desc} — "
                    f"Rs {float(amount):,.0f}. "
                    "Ensure this transaction is properly accounted for in your return."
                ),
                category="sft",
            ))

    return results


def _compare_gst_turnover(
    ais: ParsedAIS,
    gst_turnover: Decimal,
) -> list[Mismatch]:
    """Compare AIS business turnover vs GST-filed turnover."""
    results: list[Mismatch] = []
    ais_turnover = D(ais.business_turnover)

    if ais_turnover == 0 and gst_turnover == 0:
        return results

    diff = abs(ais_turnover - gst_turnover)
    base = max(ais_turnover, gst_turnover)
    if base > 0:
        pct = (diff / base) * 100
        if pct > TURNOVER_DIFF_PCT:
            results.append(Mismatch(
                field="business_turnover",
                source_a="ais",
                source_b="gst_invoices",
                value_a=ais_turnover,
                value_b=gst_turnover,
                difference=diff,
                severity="critical",
                suggested_action=(
                    f"Business turnover mismatch: AIS Rs {float(ais_turnover):,.0f} "
                    f"vs GST Rs {float(gst_turnover):,.0f} (diff {float(pct):.1f}%). "
                    "Reconcile before filing to avoid scrutiny."
                ),
                category="gst_turnover",
            ))

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_mismatches(
    form16: ParsedForm16 | None = None,
    form26as: ParsedForm26AS | None = None,
    ais: ParsedAIS | None = None,
    gst_turnover: Decimal | None = None,
) -> MismatchReport:
    """
    Compare all available documents and return a mismatch report.

    Parameters
    ----------
    form16 : ParsedForm16 or None
    form26as : ParsedForm26AS or None
    ais : ParsedAIS or None
    gst_turnover : Decimal or None
        Aggregated GST turnover for the financial year (from invoices).

    Returns
    -------
    MismatchReport
    """
    all_mismatches: list[Mismatch] = []
    docs: list[str] = []

    if form16:
        docs.append("form16")
    if form26as:
        docs.append("26as")
    if ais:
        docs.append("ais")

    # TDS comparison: Form 16 vs 26AS
    if form16 and form26as:
        all_mismatches.extend(_compare_tds(form16, form26as))

    # Salary comparison: Form 16 vs AIS
    if form16 and ais:
        all_mismatches.extend(_compare_salary(form16, ais))

    # Unreported income: Form 16 vs AIS
    if form16 and ais:
        all_mismatches.extend(_compare_income_sources(form16, ais))

    # SFT high-value transactions from AIS
    if ais:
        all_mismatches.extend(_compare_sft(ais))

    # GST turnover comparison
    has_gst = False
    if ais and gst_turnover is not None and gst_turnover > 0:
        has_gst = True
        all_mismatches.extend(_compare_gst_turnover(ais, gst_turnover))

    total_warn = sum(1 for m in all_mismatches if m.severity == "warning")
    total_crit = sum(1 for m in all_mismatches if m.severity == "critical")

    return MismatchReport(
        mismatches=all_mismatches,
        total_warnings=total_warn,
        total_critical=total_crit,
        documents_compared=docs,
        has_gst_comparison=has_gst,
    )


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def format_mismatch_report(report: MismatchReport, lang: str = "en") -> str:
    """Format a MismatchReport as WhatsApp-friendly text."""
    if not report.mismatches:
        return "No mismatches found across your documents."

    lines: list[str] = []
    lines.append(
        f"Found {len(report.mismatches)} mismatch(es) "
        f"({report.total_critical} critical, {report.total_warnings} warning):"
    )
    lines.append("")

    # Sort: critical first
    sorted_m = sorted(report.mismatches, key=lambda m: (0 if m.severity == "critical" else 1))

    for i, m in enumerate(sorted_m, 1):
        icon = "!!" if m.severity == "critical" else "!"
        lines.append(f"{i}. [{icon}] {m.field.replace('_', ' ').title()}")
        lines.append(f"   {m.source_a.upper()}: Rs {float(m.value_a):,.0f}")
        if m.source_a != m.source_b:
            lines.append(f"   {m.source_b.upper()}: Rs {float(m.value_b):,.0f}")
        lines.append(f"   Diff: Rs {float(m.difference):,.0f}")
        lines.append(f"   >> {m.suggested_action}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Serialization helpers (for session / ITRDraft storage)
# ---------------------------------------------------------------------------

def mismatch_to_dict(m: Mismatch) -> dict:
    """Serialize a Mismatch to a JSON-safe dict."""
    return {
        "field": m.field,
        "source_a": m.source_a,
        "source_b": m.source_b,
        "value_a": str(m.value_a),
        "value_b": str(m.value_b),
        "difference": str(m.difference),
        "severity": m.severity,
        "suggested_action": m.suggested_action,
        "category": m.category,
    }


def report_to_dict(report: MismatchReport) -> dict:
    """Serialize a MismatchReport to a JSON-safe dict."""
    return {
        "mismatches": [mismatch_to_dict(m) for m in report.mismatches],
        "total_warnings": report.total_warnings,
        "total_critical": report.total_critical,
        "documents_compared": report.documents_compared,
        "has_gst_comparison": report.has_gst_comparison,
    }


def dict_to_report(data: dict) -> MismatchReport:
    """Deserialize a dict back to MismatchReport."""
    if not data:
        return MismatchReport()
    mismatches = []
    for md in data.get("mismatches", []):
        mismatches.append(Mismatch(
            field=md["field"],
            source_a=md["source_a"],
            source_b=md["source_b"],
            value_a=Decimal(md["value_a"]),
            value_b=Decimal(md["value_b"]),
            difference=Decimal(md["difference"]),
            severity=md["severity"],
            suggested_action=md["suggested_action"],
            category=md["category"],
        ))
    return MismatchReport(
        mismatches=mismatches,
        total_warnings=data.get("total_warnings", 0),
        total_critical=data.get("total_critical", 0),
        documents_compared=data.get("documents_compared", []),
        has_gst_comparison=data.get("has_gst_comparison", False),
    )
