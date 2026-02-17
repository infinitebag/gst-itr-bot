# app/domain/services/itr_pdf.py
"""
Generate professional ITR-1 and ITR-4 PDF computation sheets using ReportLab.

Follows the same ReportLab patterns as invoice_pdf.py:
SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, A4 page, 15mm margins.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)

from app.domain.services.itr_service import ITR1Input, ITR4Input, ITRResult, TaxBreakdown

logger = logging.getLogger("itr_pdf")

# ---------------------------------------------------------------------------
# Shared constants — same color scheme as invoice_pdf.py
# ---------------------------------------------------------------------------
_HEADER_BG = colors.Color(0.2, 0.3, 0.5)
_LABEL_BG = colors.Color(0.95, 0.95, 0.95)
_TOTAL_ROW_BG = colors.Color(0.9, 0.95, 1.0)
_GRID_COLOR = colors.Color(0.8, 0.8, 0.8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(val: Decimal | float | int | None) -> str:
    """Format a numeric value as 'Rs X,XX,XXX' (Indian currency display)."""
    if val is None:
        return "Rs 0"
    try:
        num = float(val)
    except (ValueError, TypeError):
        return f"Rs {val}"
    if num < 0:
        return f"(Rs {abs(num):,.0f})"
    return f"Rs {num:,.0f}"


def _build_doc(buf: io.BytesIO) -> SimpleDocTemplate:
    """Create a SimpleDocTemplate with standard A4 / 15mm margins."""
    return SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )


def _get_styles() -> dict:
    """Return the shared paragraph styles used across ITR PDFs."""
    base = getSampleStyleSheet()
    return {
        "base": base,
        "title": ParagraphStyle(
            "ITRTitle",
            parent=base["Heading1"],
            fontSize=16,
            alignment=1,  # center
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "ITRSubtitle",
            parent=base["Normal"],
            fontSize=10,
            alignment=1,
            spaceAfter=20,
        ),
        "section": ParagraphStyle(
            "SectionHeader",
            parent=base["Heading2"],
            fontSize=12,
            spaceBefore=14,
            spaceAfter=6,
            textColor=_HEADER_BG,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.grey,
            alignment=1,
        ),
        "recommend": ParagraphStyle(
            "Recommend",
            parent=base["Normal"],
            fontSize=11,
            leading=16,
            spaceBefore=6,
            spaceAfter=6,
        ),
        "recommend_bold": ParagraphStyle(
            "RecommendBold",
            parent=base["Normal"],
            fontSize=11,
            leading=16,
            fontName="Helvetica-Bold",
            spaceBefore=4,
            spaceAfter=4,
        ),
    }


def _standard_table_style(*, has_header: bool = True) -> list:
    """Return a list of TableStyle commands matching invoice_pdf.py patterns."""
    cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    if has_header:
        cmds.extend([
            ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
        ])
    return cmds


def _total_row_style(row_idx: int) -> list:
    """Style commands for a total/summary row (blue-tinted background, bold)."""
    return [
        ("BACKGROUND", (0, row_idx), (-1, row_idx), _TOTAL_ROW_BG),
        ("FONTNAME", (0, row_idx), (-1, row_idx), "Helvetica-Bold"),
    ]


# ---------------------------------------------------------------------------
# Shared sections
# ---------------------------------------------------------------------------

def _add_header(elements: list, title: str, pan: str, ay: str, st: dict) -> None:
    """Add the PDF title block (title, PAN, AY, generated date)."""
    elements.append(Paragraph(title, st["title"]))
    elements.append(
        Paragraph(
            f"PAN: {pan or 'N/A'} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Assessment Year: {ay} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Generated on {datetime.now().strftime('%d-%b-%Y %H:%M')}",
            st["subtitle"],
        )
    )


def _add_deductions_table(
    elements: list,
    st: dict,
    *,
    section_80c: Decimal,
    section_80d: Decimal,
    section_80e: Decimal = Decimal("0"),
    section_80g: Decimal = Decimal("0"),
    section_80ccd_1b: Decimal = Decimal("0"),
    section_80tta: Decimal = Decimal("0"),
    other_deductions: Decimal = Decimal("0"),
    total_deductions: Decimal,
) -> None:
    """Add the Chapter VI-A deductions table."""
    elements.append(Paragraph("Part — Deductions (Chapter VI-A)", st["section"]))

    rows = [
        ["Deduction", "Amount"],
        ["Section 80C (PPF, ELSS, LIC, etc.)", _fmt(section_80c)],
        ["Section 80D (Medical Insurance)", _fmt(section_80d)],
    ]
    if section_80e:
        rows.append(["Section 80E (Education Loan Interest)", _fmt(section_80e)])
    if section_80g:
        rows.append(["Section 80G (Donations)", _fmt(section_80g)])
    if section_80ccd_1b:
        rows.append(["Section 80CCD(1B) (NPS Additional)", _fmt(section_80ccd_1b)])
    if section_80tta:
        rows.append(["Section 80TTA (Savings Interest)", _fmt(section_80tta)])
    if other_deductions:
        rows.append(["Other Deductions", _fmt(other_deductions)])
    rows.append(["Total Deductions", _fmt(total_deductions)])

    tbl = Table(rows, colWidths=[310, 150])
    style_cmds = _standard_table_style()
    style_cmds.append(("ALIGN", (1, 0), (1, -1), "RIGHT"))
    style_cmds.extend(_total_row_style(-1))
    tbl.setStyle(TableStyle(style_cmds))
    elements.append(tbl)
    elements.append(Spacer(1, 12))


def _add_tax_computation_table(
    elements: list,
    st: dict,
    old: TaxBreakdown,
    new: TaxBreakdown,
) -> None:
    """Add the two-column Old vs New regime tax computation table."""
    elements.append(Paragraph("Part — Tax Computation", st["section"]))

    rows = [
        ["Particulars", "Old Regime", "New Regime"],
        ["Taxable Income", _fmt(old.taxable_income), _fmt(new.taxable_income)],
        ["Tax on Income", _fmt(old.tax_on_income), _fmt(new.tax_on_income)],
        ["Less: Rebate u/s 87A", _fmt(old.rebate_87a), _fmt(new.rebate_87a)],
        ["Surcharge", _fmt(old.surcharge), _fmt(new.surcharge)],
        ["Health & Edu Cess (4%)", _fmt(old.health_cess), _fmt(new.health_cess)],
        ["Total Tax Liability", _fmt(old.total_tax_liability), _fmt(new.total_tax_liability)],
        ["Taxes Already Paid", _fmt(old.taxes_paid), _fmt(new.taxes_paid)],
    ]

    # Tax payable / refund row
    old_label = "Tax Payable" if old.tax_payable >= 0 else "Refund Due"
    new_label = "Tax Payable" if new.tax_payable >= 0 else "Refund Due"
    old_val = _fmt(abs(old.tax_payable))
    new_val = _fmt(abs(new.tax_payable))
    if old.tax_payable < 0:
        old_val = f"({old_val})"
    if new.tax_payable < 0:
        new_val = f"({new_val})"
    rows.append([f"{old_label} / {new_label}", old_val, new_val])

    tbl = Table(rows, colWidths=[220, 120, 120])
    style_cmds = _standard_table_style()
    style_cmds.extend([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ])
    # Bold the total-tax-liability row (row index 6) and the payable/refund row (last)
    style_cmds.extend(_total_row_style(7))   # Total Tax Liability row (index 6 is 7th row, 0-based in data but 0=header)
    style_cmds.extend(_total_row_style(-1))  # Tax Payable / Refund row
    tbl.setStyle(TableStyle(style_cmds))
    elements.append(tbl)
    elements.append(Spacer(1, 12))


def _add_recommended_regime(
    elements: list,
    st: dict,
    recommended: str,
    savings: Decimal,
) -> None:
    """Add the recommended regime section."""
    elements.append(Paragraph("Part — Recommended Regime", st["section"]))

    regime_display = "New Regime" if recommended == "new" else "Old Regime"
    elements.append(
        Paragraph(
            f"<b>Recommended: {regime_display}</b>",
            st["recommend_bold"],
        )
    )
    if savings > 0:
        elements.append(
            Paragraph(
                f"By choosing the <b>{regime_display}</b>, you save approximately "
                f"<b>{_fmt(savings)}</b> compared to the other regime.",
                st["recommend"],
            )
        )
    else:
        elements.append(
            Paragraph(
                "Both regimes result in the same tax liability.",
                st["recommend"],
            )
        )
    elements.append(Spacer(1, 12))


def _add_footer(elements: list, st: dict) -> None:
    """Add the standard disclaimer footer."""
    elements.append(
        Paragraph(
            "This is a computer-generated ITR computation. "
            "Please verify with a CA before filing.",
            st["footer"],
        )
    )


# ---------------------------------------------------------------------------
# ITR-1 (Sahaj) PDF
# ---------------------------------------------------------------------------

def generate_itr1_pdf(inp: ITR1Input, result: ITRResult) -> bytes:
    """
    Generate a professional ITR-1 (Sahaj) computation PDF.

    Args:
        inp: The ITR-1 input data (salary, deductions, etc.).
        result: The computed ITRResult with old/new regime breakdowns.

    Returns:
        PDF file as bytes.
    """
    buf = io.BytesIO()
    doc = _build_doc(buf)
    st = _get_styles()
    elements: list = []

    # ---- Header ----
    _add_header(
        elements,
        "INCOME TAX RETURN — ITR-1 (SAHAJ)",
        inp.pan,
        inp.assessment_year,
        st,
    )

    # ---- Part A: Income Details ----
    elements.append(Paragraph("Part A — Income Details", st["section"]))

    net_salary = max(inp.salary_income - inp.standard_deduction, Decimal("0"))
    gross_total = net_salary + inp.house_property_income + inp.other_income

    income_rows = [
        ["Income Head", "Amount"],
        ["Gross Salary", _fmt(inp.salary_income)],
        ["Less: Standard Deduction u/s 16(ia)", _fmt(inp.standard_deduction)],
        ["Net Salary", _fmt(net_salary)],
        ["Income from House Property", _fmt(inp.house_property_income)],
        ["Income from Other Sources", _fmt(inp.other_income)],
        ["Gross Total Income", _fmt(gross_total)],
    ]

    income_tbl = Table(income_rows, colWidths=[310, 150])
    style_cmds = _standard_table_style()
    style_cmds.extend([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ])
    style_cmds.extend(_total_row_style(-1))  # Gross Total Income row
    income_tbl.setStyle(TableStyle(style_cmds))
    elements.append(income_tbl)
    elements.append(Spacer(1, 12))

    # ---- Part B: Deductions ----
    old = result.old_regime
    _add_deductions_table(
        elements,
        st,
        section_80c=inp.section_80c,
        section_80d=inp.section_80d,
        section_80e=inp.section_80e,
        section_80g=inp.section_80g,
        section_80ccd_1b=inp.section_80ccd_1b,
        section_80tta=inp.section_80tta,
        other_deductions=inp.other_deductions,
        total_deductions=old.total_deductions if old else Decimal("0"),
    )

    # ---- Part C: Tax Computation (Old vs New) ----
    if result.old_regime and result.new_regime:
        _add_tax_computation_table(elements, st, result.old_regime, result.new_regime)

    # ---- Part D: Recommended Regime ----
    _add_recommended_regime(elements, st, result.recommended_regime, result.savings)

    # ---- Footer ----
    _add_footer(elements, st)

    doc.build(elements)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ITR-4 (Sugam) PDF
# ---------------------------------------------------------------------------

def generate_itr4_pdf(inp: ITR4Input, result: ITRResult) -> bytes:
    """
    Generate a professional ITR-4 (Sugam) computation PDF.

    Args:
        inp: The ITR-4 input data (turnover, presumptive rates, etc.).
        result: The computed ITRResult with old/new regime breakdowns.

    Returns:
        PDF file as bytes.
    """
    buf = io.BytesIO()
    doc = _build_doc(buf)
    st = _get_styles()
    elements: list = []

    # ---- Header ----
    _add_header(
        elements,
        "INCOME TAX RETURN — ITR-4 (SUGAM)",
        inp.pan,
        inp.assessment_year,
        st,
    )

    # ---- Part A: Business Income ----
    elements.append(Paragraph("Part A — Business Income", st["section"]))

    deemed_profit = inp.gross_turnover * inp.presumptive_rate / 100
    professional_income = inp.gross_receipts * inp.professional_rate / 100

    biz_rows = [
        ["Particulars", "Amount"],
        ["Gross Turnover (u/s 44AD)", _fmt(inp.gross_turnover)],
        [f"Presumptive Rate ({inp.presumptive_rate}%)", f"{inp.presumptive_rate}%"],
        ["Deemed Profit from Business", _fmt(deemed_profit)],
        ["Professional Gross Receipts (u/s 44ADA)", _fmt(inp.gross_receipts)],
        [f"Professional Rate ({inp.professional_rate}%)", f"{inp.professional_rate}%"],
        ["Professional Income", _fmt(professional_income)],
    ]

    biz_tbl = Table(biz_rows, colWidths=[310, 150])
    style_cmds = _standard_table_style()
    style_cmds.extend([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ])
    # Highlight the deemed profit row (row 3) and professional income row (row 6)
    style_cmds.extend(_total_row_style(4))   # Deemed Profit (index 3 data = row 4 with header)
    style_cmds.extend(_total_row_style(-1))  # Professional Income
    biz_tbl.setStyle(TableStyle(style_cmds))
    elements.append(biz_tbl)
    elements.append(Spacer(1, 12))

    # ---- Part B: Other Income ----
    elements.append(Paragraph("Part B — Other Income", st["section"]))

    salary_after_std = max(inp.salary_income - Decimal("75000"), Decimal("0"))
    total_other = salary_after_std + inp.house_property_income + inp.other_income

    other_rows = [
        ["Income Head", "Amount"],
        ["Salary Income (after Std Deduction)", _fmt(salary_after_std)],
        ["Income from House Property", _fmt(inp.house_property_income)],
        ["Income from Other Sources", _fmt(inp.other_income)],
        ["Total Other Income", _fmt(total_other)],
    ]

    other_tbl = Table(other_rows, colWidths=[310, 150])
    style_cmds = _standard_table_style()
    style_cmds.extend([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ])
    style_cmds.extend(_total_row_style(-1))
    other_tbl.setStyle(TableStyle(style_cmds))
    elements.append(other_tbl)
    elements.append(Spacer(1, 12))

    # ---- Part C: Deductions ----
    old = result.old_regime
    _add_deductions_table(
        elements,
        st,
        section_80c=inp.section_80c,
        section_80d=inp.section_80d,
        other_deductions=inp.other_deductions,
        total_deductions=old.total_deductions if old else Decimal("0"),
    )

    # ---- Part D: Tax Computation (Old vs New) ----
    if result.old_regime and result.new_regime:
        _add_tax_computation_table(elements, st, result.old_regime, result.new_regime)

    # ---- Part E: Recommended Regime ----
    _add_recommended_regime(elements, st, result.recommended_regime, result.savings)

    # ---- Footer ----
    _add_footer(elements, st)

    doc.build(elements)
    return buf.getvalue()
