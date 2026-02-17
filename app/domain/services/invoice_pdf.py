# app/domain/services/invoice_pdf.py
"""
Generate GST-compliant invoice PDFs from parsed invoice data.
Uses ReportLab for PDF generation.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime

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

logger = logging.getLogger("invoice_pdf")


def generate_invoice_pdf(invoice_data: dict) -> bytes:
    """
    Generate a GST-compliant invoice PDF from parsed invoice data.

    Args:
        invoice_data: Dict with keys like supplier_gstin, receiver_gstin,
                      invoice_number, invoice_date, taxable_value,
                      tax_amount, total_amount, cgst_amount, sgst_amount,
                      igst_amount, place_of_supply.

    Returns:
        PDF file as bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=1,  # center
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "InvoiceSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        alignment=1,
        spaceAfter=20,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.grey,
    )
    value_style = ParagraphStyle(
        "Value",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
    )

    elements = []

    # Title
    elements.append(Paragraph("TAX INVOICE", title_style))
    elements.append(
        Paragraph(
            f"Generated on {datetime.now().strftime('%d-%b-%Y %H:%M')}",
            subtitle_style,
        )
    )

    # Invoice details table
    inv_no = invoice_data.get("invoice_number") or "N/A"
    inv_date = invoice_data.get("invoice_date") or "N/A"
    supplier_gstin = invoice_data.get("supplier_gstin") or "N/A"
    receiver_gstin = invoice_data.get("receiver_gstin") or "N/A"
    place_of_supply = invoice_data.get("place_of_supply") or "N/A"

    header_data = [
        ["Invoice Number", inv_no, "Invoice Date", str(inv_date)],
        ["Supplier GSTIN", supplier_gstin, "Receiver GSTIN", receiver_gstin],
        ["Place of Supply", place_of_supply, "", ""],
    ]

    header_table = Table(header_data, colWidths=[90, 140, 90, 140])
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
                ("BACKGROUND", (2, 0), (2, -1), colors.Color(0.95, 0.95, 0.95)),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 15))

    # Amount breakdown
    def _fmt_amount(val) -> str:
        if val is None:
            return "0.00"
        try:
            return f"{float(val):,.2f}"
        except (ValueError, TypeError):
            return str(val)

    taxable = invoice_data.get("taxable_value")
    cgst = invoice_data.get("cgst_amount")
    sgst = invoice_data.get("sgst_amount")
    igst = invoice_data.get("igst_amount")
    tax_total = invoice_data.get("tax_amount")
    total = invoice_data.get("total_amount")

    amount_rows = [
        ["Description", "Amount (Rs)"],
        ["Taxable Value", _fmt_amount(taxable)],
    ]

    if cgst:
        amount_rows.append(["CGST", _fmt_amount(cgst)])
    if sgst:
        amount_rows.append(["SGST", _fmt_amount(sgst)])
    if igst:
        amount_rows.append(["IGST", _fmt_amount(igst)])

    amount_rows.append(["Total Tax", _fmt_amount(tax_total)])
    amount_rows.append(["TOTAL AMOUNT", _fmt_amount(total)])

    amount_table = Table(amount_rows, colWidths=[300, 160])
    amount_table.setStyle(
        TableStyle(
            [
                # Header row
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.2, 0.3, 0.5)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                # Total row (last row)
                ("BACKGROUND", (0, -1), (-1, -1), colors.Color(0.9, 0.95, 1.0)),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                # General
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    elements.append(amount_table)
    elements.append(Spacer(1, 20))

    # Footer
    elements.append(
        Paragraph(
            "This is a computer-generated invoice summary. "
            "Please verify with the original document.",
            ParagraphStyle(
                "Footer",
                parent=styles["Normal"],
                fontSize=8,
                textColor=colors.grey,
                alignment=1,
            ),
        )
    )

    doc.build(elements)
    return buf.getvalue()


def generate_multi_invoice_summary_pdf(invoices: list[dict]) -> bytes:
    """
    Generate a summary PDF for multiple invoices.

    Args:
        invoices: List of invoice dicts.

    Returns:
        PDF file as bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SummaryTitle",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=1,
        spaceAfter=10,
    )

    elements = []
    elements.append(Paragraph("INVOICE SUMMARY REPORT", title_style))
    elements.append(
        Paragraph(
            f"Generated on {datetime.now().strftime('%d-%b-%Y %H:%M')} | "
            f"Total Invoices: {len(invoices)}",
            ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, alignment=1, spaceAfter=20),
        )
    )

    # Summary table
    def _safe_float(val) -> float:
        try:
            return float(val) if val else 0.0
        except (ValueError, TypeError):
            return 0.0

    header = [
        "Invoice No",
        "Date",
        "Supplier GSTIN",
        "Taxable",
        "Tax",
        "Total",
    ]
    rows = [header]

    grand_taxable = 0.0
    grand_tax = 0.0
    grand_total = 0.0

    for inv in invoices:
        taxable = _safe_float(inv.get("taxable_value"))
        tax = _safe_float(inv.get("tax_amount"))
        total = _safe_float(inv.get("total_amount"))
        grand_taxable += taxable
        grand_tax += tax
        grand_total += total

        rows.append([
            str(inv.get("invoice_number") or "N/A")[:15],
            str(inv.get("invoice_date") or "N/A")[:12],
            str(inv.get("supplier_gstin") or "N/A")[:15],
            f"{taxable:,.0f}",
            f"{tax:,.0f}",
            f"{total:,.0f}",
        ])

    # Grand total row
    rows.append([
        "TOTAL", "", "",
        f"{grand_taxable:,.0f}",
        f"{grand_tax:,.0f}",
        f"{grand_total:,.0f}",
    ])

    col_widths = [75, 65, 95, 70, 60, 75]
    summary_table = Table(rows, colWidths=col_widths)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.2, 0.3, 0.5)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, -1), (-1, -1), colors.Color(0.9, 0.95, 1.0)),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 15))

    elements.append(
        Paragraph(
            "This is a computer-generated summary report.",
            ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=1),
        )
    )

    doc.build(elements)
    return buf.getvalue()
