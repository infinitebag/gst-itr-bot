# app/domain/services/gst_explainer.py
"""
GST explainer service — generates simple "Why this amount?" explanations
and segment-aware summary formatting for the WhatsApp wizard flow.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.domain.i18n import t, t_segment

logger = logging.getLogger("gst_explainer")


def explain_liability(
    sales_tax: float,
    purchase_credit: float,
    lang: str = "en",
) -> str:
    """Generate a 'Why this amount?' explanation in simple language.

    Example output:
        💡 *Why this amount?*
        Your sales tax is ₹15,300.
        Purchase credit is ₹8,200.
        Amount to pay = ₹15,300 - ₹8,200 = ₹7,100
    """
    net_amount = max(0.0, sales_tax - purchase_credit)
    return t(
        "GST_WHY_THIS_AMOUNT",
        lang,
        sales_tax=f"{sales_tax:,.2f}",
        purchase_credit=f"{purchase_credit:,.2f}",
        net_amount=f"{net_amount:,.2f}",
    )


def detect_nil_return(invoices: list[dict]) -> bool:
    """Auto-detect if this should be a NIL return (no invoices).

    Returns True if the invoice list is empty or all have zero amounts.
    """
    if not invoices:
        return True
    total = sum(
        float(inv.get("total_amount", 0) or 0)
        for inv in invoices
    )
    return total == 0.0


def compute_sales_tax(invoices: list[dict]) -> float:
    """Sum up total tax from sales invoices."""
    total = 0.0
    for inv in invoices:
        cgst = float(inv.get("cgst_amount", 0) or 0)
        sgst = float(inv.get("sgst_amount", 0) or 0)
        igst = float(inv.get("igst_amount", 0) or 0)
        total += cgst + sgst + igst
    return total


def compute_purchase_credit(invoices: list[dict]) -> float:
    """Sum up ITC (purchase credit) from purchase invoices."""
    total = 0.0
    for inv in invoices:
        cgst = float(inv.get("cgst_amount", 0) or 0)
        sgst = float(inv.get("sgst_amount", 0) or 0)
        igst = float(inv.get("igst_amount", 0) or 0)
        total += cgst + sgst + igst
    return total


def format_simple_summary(
    sales_invoices: list[dict],
    purchase_invoices: list[dict],
    lang: str = "en",
    segment: str = "small",
) -> str:
    """Build a segment-aware GST summary in simple language.

    For small segment: uses simple terms (Sales Tax, Purchase Credit, Amount to Pay).
    For medium/enterprise: adds more detail.
    """
    sales_tax = compute_sales_tax(sales_invoices)
    purchase_credit = compute_purchase_credit(purchase_invoices)
    net_amount = max(0.0, sales_tax - purchase_credit)

    explainer = explain_liability(sales_tax, purchase_credit, lang)

    return t(
        "WIZARD_SUMMARY",
        lang,
        sales_tax=f"{sales_tax:,.2f}",
        purchase_credit=f"{purchase_credit:,.2f}",
        net_amount=f"{net_amount:,.2f}",
        explainer=explainer,
    )


def format_risk_factors(assessment) -> str:
    """Format risk assessment factors for WhatsApp display.

    Parameters
    ----------
    assessment
        RiskAssessment ORM object with ``factor_scores`` JSON field.
    """
    factors = getattr(assessment, "factor_scores", None)
    if not factors or not isinstance(factors, dict):
        return "No detailed factors available."

    lines = []
    for factor, score in sorted(factors.items(), key=lambda x: -x[1]):
        if score > 0.7:
            emoji = "🔴"
        elif score > 0.4:
            emoji = "🟡"
        else:
            emoji = "🟢"
        # Convert factor_name to readable form
        readable = factor.replace("_", " ").title()
        lines.append(f"{emoji} {readable}: {score:.0%}")

    return "\n".join(lines[:5])  # Show top 5 factors
