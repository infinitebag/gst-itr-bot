# app/domain/services/tax_analytics.py
"""
AI-powered tax analytics and insights service.
Aggregates invoice data and uses GPT-4o to generate actionable insights.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.infrastructure.external.openai_client import _get_client
from app.config.settings import settings

logger = logging.getLogger("tax_analytics")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class TaxSummary:
    """Aggregated tax data for a period."""

    period_start: date
    period_end: date
    total_invoices: int = 0
    total_taxable_value: Decimal = Decimal("0.00")
    total_tax: Decimal = Decimal("0.00")
    total_cgst: Decimal = Decimal("0.00")
    total_sgst: Decimal = Decimal("0.00")
    total_igst: Decimal = Decimal("0.00")
    total_amount: Decimal = Decimal("0.00")
    b2b_count: int = 0
    b2c_count: int = 0
    unique_suppliers: int = 0
    unique_receivers: int = 0
    avg_invoice_value: Decimal = Decimal("0.00")
    tax_rate_distribution: dict = field(default_factory=dict)


@dataclass
class AnomalyReport:
    """Invoice anomaly detection results."""

    duplicate_invoice_numbers: list[dict] = field(default_factory=list)
    invalid_gstins: list[dict] = field(default_factory=list)
    high_value_invoices: list[dict] = field(default_factory=list)
    missing_fields: list[dict] = field(default_factory=list)
    tax_rate_outliers: list[dict] = field(default_factory=list)
    total_anomalies: int = 0


@dataclass
class FilingDeadline:
    """Tax filing deadline information."""

    form_name: str
    due_date: date
    period: str
    days_remaining: int
    status: str  # "upcoming", "due_soon", "overdue"
    description: str = ""


# ---------------------------------------------------------------------------
# Aggregation (pure Python, no DB dependency)
# ---------------------------------------------------------------------------
def aggregate_invoices(invoices: list[Any]) -> TaxSummary:
    """
    Aggregate a list of Invoice ORM objects (or dicts) into a TaxSummary.
    Works with SQLAlchemy Invoice models or plain dicts.
    """
    today = date.today()
    summary = TaxSummary(
        period_start=today.replace(day=1),
        period_end=today,
    )

    suppliers = set()
    receivers = set()
    rate_counts: dict[str, int] = {}

    for inv in invoices:
        # Support both ORM objects and dicts
        get = inv.get if isinstance(inv, dict) else lambda k, d=None: getattr(inv, k, d)

        summary.total_invoices += 1

        taxable = _to_decimal(get("taxable_value", 0))
        tax = _to_decimal(get("tax_amount", 0))
        total = _to_decimal(get("total_amount", 0))
        cgst = _to_decimal(get("cgst_amount", 0))
        sgst = _to_decimal(get("sgst_amount", 0))
        igst = _to_decimal(get("igst_amount", 0))

        summary.total_taxable_value += taxable
        summary.total_tax += tax
        summary.total_amount += total
        summary.total_cgst += cgst
        summary.total_sgst += sgst
        summary.total_igst += igst

        # B2B vs B2C
        recipient = get("recipient_gstin") or get("receiver_gstin")
        if recipient and len(str(recipient)) == 15:
            summary.b2b_count += 1
        else:
            summary.b2c_count += 1

        # Unique parties
        supplier = get("supplier_gstin")
        if supplier:
            suppliers.add(supplier)
        if recipient:
            receivers.add(str(recipient))

        # Tax rate distribution
        rate = get("tax_rate")
        if rate is not None:
            rate_key = str(float(rate))
            rate_counts[rate_key] = rate_counts.get(rate_key, 0) + 1

        # Period tracking
        inv_date = get("invoice_date")
        if inv_date:
            if isinstance(inv_date, datetime):
                inv_date = inv_date.date()
            if isinstance(inv_date, date):
                if inv_date < summary.period_start:
                    summary.period_start = inv_date
                if inv_date > summary.period_end:
                    summary.period_end = inv_date

    summary.unique_suppliers = len(suppliers)
    summary.unique_receivers = len(receivers)
    summary.tax_rate_distribution = rate_counts

    if summary.total_invoices > 0:
        summary.avg_invoice_value = summary.total_amount / summary.total_invoices

    return summary


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------
def detect_anomalies(
    invoices: list[Any],
    valid_gst_rates: set[float] | None = None,
) -> AnomalyReport:
    """Detect common invoice anomalies.

    Args:
        valid_gst_rates: Optional custom set of valid GST rates.
                         If ``None``, uses the hardcoded default set.
    """
    report = AnomalyReport()

    invoice_numbers: dict[str, list[int]] = {}
    values: list[Decimal] = []

    for i, inv in enumerate(invoices):
        get = inv.get if isinstance(inv, dict) else lambda k, d=None: getattr(inv, k, d)

        # Check for duplicate invoice numbers
        inv_num = get("invoice_number")
        if inv_num:
            invoice_numbers.setdefault(inv_num, []).append(i)

        # Track values for outlier detection
        total = _to_decimal(get("total_amount", 0))
        values.append(total)

        # Check for invalid GSTINs
        supplier = get("supplier_gstin")
        supplier_valid = get("supplier_gstin_valid")
        if supplier and supplier_valid is False:
            report.invalid_gstins.append({
                "index": i,
                "invoice_number": inv_num,
                "field": "supplier_gstin",
                "value": supplier,
            })

        receiver_valid = get("receiver_gstin_valid")
        receiver = get("receiver_gstin")
        if receiver and receiver_valid is False:
            report.invalid_gstins.append({
                "index": i,
                "invoice_number": inv_num,
                "field": "receiver_gstin",
                "value": receiver,
            })

        # Check for missing critical fields
        missing = []
        if not get("invoice_number"):
            missing.append("invoice_number")
        if not get("invoice_date"):
            missing.append("invoice_date")
        if _to_decimal(get("taxable_value", 0)) == 0 and _to_decimal(get("total_amount", 0)) == 0:
            missing.append("amounts")
        if missing:
            report.missing_fields.append({
                "index": i,
                "invoice_number": inv_num or "N/A",
                "missing": missing,
            })

        # Tax rate outliers (unusual rates)
        rate = get("tax_rate")
        if rate is not None:
            rate_f = float(rate)
            _valid = valid_gst_rates or {0, 0.1, 0.25, 1.5, 3, 5, 6, 7.5, 12, 14, 18, 28}
            if rate_f not in _valid and rate_f > 0:
                report.tax_rate_outliers.append({
                    "index": i,
                    "invoice_number": inv_num,
                    "tax_rate": rate_f,
                })

    # Duplicate invoice numbers
    for inv_num, indices in invoice_numbers.items():
        if len(indices) > 1:
            report.duplicate_invoice_numbers.append({
                "invoice_number": inv_num,
                "count": len(indices),
                "indices": indices,
            })

    # High-value outliers (> 3x the mean)
    if values:
        mean_val = sum(values) / len(values) if values else Decimal("0")
        threshold = mean_val * 3
        if threshold > 0:
            for i, val in enumerate(values):
                if val > threshold:
                    get = invoices[i].get if isinstance(invoices[i], dict) else lambda k, d=None: getattr(invoices[i], k, d)
                    report.high_value_invoices.append({
                        "index": i,
                        "invoice_number": get("invoice_number"),
                        "total_amount": float(val),
                        "mean_amount": float(mean_val),
                    })

    report.total_anomalies = (
        len(report.duplicate_invoice_numbers)
        + len(report.invalid_gstins)
        + len(report.high_value_invoices)
        + len(report.missing_fields)
        + len(report.tax_rate_outliers)
    )

    return report


# ---------------------------------------------------------------------------
# Filing deadline calculator
# ---------------------------------------------------------------------------
def get_filing_deadlines(reference_date: date | None = None) -> list[FilingDeadline]:
    """
    Calculate upcoming GST/ITR filing deadlines based on Indian tax calendar.
    """
    today = reference_date or date.today()
    deadlines: list[FilingDeadline] = []

    # Current month/year context
    year = today.year
    month = today.month

    # GST deadlines
    gst_deadlines = [
        # GSTR-1: 11th of next month (for regular taxpayers)
        {
            "form": "GSTR-1",
            "day": 11,
            "offset_months": 1,
            "desc": "Monthly return for outward supplies",
        },
        # GSTR-3B: 20th of next month
        {
            "form": "GSTR-3B",
            "day": 20,
            "offset_months": 1,
            "desc": "Monthly self-assessed return",
        },
        # GSTR-1 (QRMP): 13th of month after quarter end
        {
            "form": "GSTR-1 (Quarterly)",
            "day": 13,
            "offset_months": 1,
            "desc": "Quarterly return for small taxpayers (QRMP)",
        },
    ]

    for gst in gst_deadlines:
        due_month = month + gst["offset_months"]
        due_year = year
        if due_month > 12:
            due_month -= 12
            due_year += 1

        try:
            due = date(due_year, due_month, gst["day"])
        except ValueError:
            # Handle months with fewer days
            due = date(due_year, due_month, 28)

        period_str = f"{_month_name(month)} {year}"
        days_rem = (due - today).days

        if days_rem < 0:
            status = "overdue"
        elif days_rem <= 5:
            status = "due_soon"
        else:
            status = "upcoming"

        deadlines.append(FilingDeadline(
            form_name=gst["form"],
            due_date=due,
            period=period_str,
            days_remaining=days_rem,
            status=status,
            description=gst["desc"],
        ))

    # ITR deadline (July 31 for non-audit, October 31 for audit)
    fy_end_year = year if month >= 4 else year - 1  # FY ends in March
    itr_due = date(fy_end_year + 1, 7, 31)
    itr_days = (itr_due - today).days

    if itr_days < 0:
        itr_status = "overdue"
    elif itr_days <= 30:
        itr_status = "due_soon"
    else:
        itr_status = "upcoming"

    deadlines.append(FilingDeadline(
        form_name="ITR-1/ITR-4",
        due_date=itr_due,
        period=f"FY {fy_end_year}-{(fy_end_year + 1) % 100:02d}",
        days_remaining=itr_days,
        status=itr_status,
        description="Annual income tax return for individuals/HUF",
    ))

    # Sort by due date
    deadlines.sort(key=lambda d: d.due_date)

    return deadlines


# ---------------------------------------------------------------------------
# AI-powered insights generation
# ---------------------------------------------------------------------------
INSIGHTS_SYSTEM_PROMPT = """\
You are an Indian tax analytics expert. Given tax summary data and anomaly reports, \
generate actionable insights for a small business owner or their Chartered Accountant.

Rules:
1. Answer in the SAME language specified in the request
2. Keep insights concise and actionable (WhatsApp format, under 400 words)
3. Highlight key numbers with context
4. Flag any anomalies or concerns
5. Suggest specific actions (e.g. "claim ITC before filing", "verify GSTIN")
6. Include filing deadline reminders if relevant
7. Use bullet points for clarity
8. Reference relevant GST/ITR sections when applicable\
"""


# Whitelist of supported languages for LLM prompts
_ALLOWED_LANGS = {"en", "hi", "gu", "ta", "te", "kn", "mr", "bn", "ml", "pa"}


def _sanitize_lang(lang: str) -> str:
    """Validate lang against whitelist to prevent prompt injection."""
    lang = (lang or "en").strip().lower()[:5]
    return lang if lang in _ALLOWED_LANGS else "en"


async def generate_ai_insights(
    summary: TaxSummary,
    anomalies: AnomalyReport,
    deadlines: list[FilingDeadline],
    lang: str = "en",
) -> str:
    """
    Use GPT-4o to generate AI-powered tax insights from aggregated data.
    """
    if not settings.OPENAI_API_KEY:
        return _fallback_insights(summary, anomalies, deadlines)

    try:
        # Build data context for the LLM
        data_context = {
            "summary": {
                "period": f"{summary.period_start} to {summary.period_end}",
                "total_invoices": summary.total_invoices,
                "total_taxable_value": float(summary.total_taxable_value),
                "total_tax_collected": float(summary.total_tax),
                "total_cgst": float(summary.total_cgst),
                "total_sgst": float(summary.total_sgst),
                "total_igst": float(summary.total_igst),
                "b2b_invoices": summary.b2b_count,
                "b2c_invoices": summary.b2c_count,
                "unique_suppliers": summary.unique_suppliers,
                "unique_receivers": summary.unique_receivers,
                "avg_invoice_value": float(summary.avg_invoice_value),
            },
            "anomalies": {
                "total_anomalies": anomalies.total_anomalies,
                "duplicate_invoices": len(anomalies.duplicate_invoice_numbers),
                "invalid_gstins": len(anomalies.invalid_gstins),
                "high_value_outliers": len(anomalies.high_value_invoices),
                "missing_fields": len(anomalies.missing_fields),
                "unusual_tax_rates": len(anomalies.tax_rate_outliers),
            },
            "deadlines": [
                {
                    "form": d.form_name,
                    "due_date": str(d.due_date),
                    "days_remaining": d.days_remaining,
                    "status": d.status,
                }
                for d in deadlines[:5]
            ],
        }

        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"[lang={_sanitize_lang(lang)}] Generate tax insights from this data:\n"
                        f"{json.dumps(data_context, indent=2)}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        return response.choices[0].message.content or _fallback_insights(
            summary, anomalies, deadlines
        )
    except Exception:
        logger.exception("AI insights generation failed")
        return _fallback_insights(summary, anomalies, deadlines)


def _fallback_insights(
    summary: TaxSummary,
    anomalies: AnomalyReport,
    deadlines: list[FilingDeadline],
) -> str:
    """Non-AI fallback: structured summary when OpenAI is unavailable."""
    lines = [
        "Tax Summary",
        f"Period: {summary.period_start} to {summary.period_end}",
        f"Total Invoices: {summary.total_invoices}",
        f"Taxable Value: Rs.{summary.total_taxable_value:,.2f}",
        f"Total Tax: Rs.{summary.total_tax:,.2f}",
        f"  CGST: Rs.{summary.total_cgst:,.2f}",
        f"  SGST: Rs.{summary.total_sgst:,.2f}",
        f"  IGST: Rs.{summary.total_igst:,.2f}",
        f"B2B: {summary.b2b_count} | B2C: {summary.b2c_count}",
        "",
    ]

    if anomalies.total_anomalies > 0:
        lines.append(f"Anomalies Found: {anomalies.total_anomalies}")
        if anomalies.duplicate_invoice_numbers:
            lines.append(f"  Duplicate invoice numbers: {len(anomalies.duplicate_invoice_numbers)}")
        if anomalies.invalid_gstins:
            lines.append(f"  Invalid GSTINs: {len(anomalies.invalid_gstins)}")
        if anomalies.high_value_invoices:
            lines.append(f"  High-value outliers: {len(anomalies.high_value_invoices)}")
        lines.append("")

    if deadlines:
        lines.append("Upcoming Deadlines:")
        for d in deadlines[:3]:
            emoji = {"overdue": "!!!", "due_soon": "!!", "upcoming": ""}[d.status]
            lines.append(f"  {d.form_name}: {d.due_date} ({d.days_remaining}d) {emoji}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_decimal(val: Any) -> Decimal:
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _month_name(month: int) -> str:
    months = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    return months[month] if 1 <= month <= 12 else str(month)


# ---------------------------------------------------------------------------
# Async wrapper (auto-resolve dynamic GST rates)
# ---------------------------------------------------------------------------

async def detect_anomalies_dynamic(invoices: list[Any]) -> AnomalyReport:
    """Async wrapper — resolves GST rates dynamically, then detects anomalies."""
    from app.domain.services.tax_rate_service import get_tax_rate_service

    service = get_tax_rate_service()
    gst_config = await service.get_gst_rates()
    return detect_anomalies(invoices, valid_gst_rates=gst_config.valid_rates)
