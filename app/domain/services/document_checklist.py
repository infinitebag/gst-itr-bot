# app/domain/services/document_checklist.py
"""
Supporting Document Checklist Generator for ITR filing.

Automatically generates a list of required/recommended documents based on
the income types and deductions detected in MergedITRData.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.services.itr_form_parser import MergedITRData

logger = logging.getLogger("document_checklist")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChecklistItem:
    """A single document requirement."""
    document: str        # e.g. "Form 16", "Investment Proofs (80C)"
    reason: str          # e.g. "You have salary income of Rs 12,00,000"
    status: str          # "uploaded" | "missing" | "recommended"
    priority: str        # "required" | "recommended" | "optional"


@dataclass
class DocumentChecklist:
    """Complete checklist for an ITR filing."""
    items: list[ChecklistItem] = field(default_factory=list)
    uploaded_count: int = 0
    missing_required: int = 0
    missing_recommended: int = 0


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_checklist(
    merged: MergedITRData,
    uploaded_docs: list[str] | None = None,
) -> DocumentChecklist:
    """
    Generate a supporting document checklist based on income/deduction data.

    Parameters
    ----------
    merged : MergedITRData
        The merged data from uploaded documents.
    uploaded_docs : list[str] or None
        List of document types already uploaded (e.g. ["form16", "26as", "ais"]).

    Returns
    -------
    DocumentChecklist
    """
    uploaded = set(uploaded_docs or merged.sources or [])
    items: list[ChecklistItem] = []

    # ---- Form 16 (employer TDS certificate) ----
    if merged.salary_income > 0:
        items.append(ChecklistItem(
            document="Form 16",
            reason=f"You have salary income of Rs {float(merged.salary_income):,.0f}",
            status="uploaded" if "form16" in uploaded else "missing",
            priority="required",
        ))

    # ---- Form 26AS (tax credit statement) — always recommended ----
    items.append(ChecklistItem(
        document="Form 26AS",
        reason="Authoritative source for TDS, advance tax, and self-assessment tax",
        status="uploaded" if "26as" in uploaded else "missing",
        priority="required",
    ))

    # ---- AIS (Annual Information Statement) — always recommended ----
    items.append(ChecklistItem(
        document="AIS (Annual Information Statement)",
        reason="Catches unreported income (interest, dividends, SFT transactions)",
        status="uploaded" if "ais" in uploaded else "recommended",
        priority="recommended",
    ))

    # ---- Section 80C investment proofs ----
    if merged.section_80c > 0:
        items.append(ChecklistItem(
            document="Investment Proofs (Section 80C)",
            reason=(
                f"80C deduction of Rs {float(merged.section_80c):,.0f} claimed — "
                "PPF receipts, ELSS statements, LIC premium receipts, etc."
            ),
            status="recommended",
            priority="recommended",
        ))

    # ---- Section 80D health insurance ----
    if merged.section_80d > 0:
        items.append(ChecklistItem(
            document="Health Insurance Premium Receipts (Section 80D)",
            reason=f"80D deduction of Rs {float(merged.section_80d):,.0f} claimed",
            status="recommended",
            priority="recommended",
        ))

    # ---- Section 80E education loan ----
    if merged.section_80e > 0:
        items.append(ChecklistItem(
            document="Education Loan Interest Certificate (Section 80E)",
            reason=f"80E deduction of Rs {float(merged.section_80e):,.0f} claimed",
            status="recommended",
            priority="recommended",
        ))

    # ---- Section 80G donations ----
    if merged.section_80g > 0:
        items.append(ChecklistItem(
            document="Donation Receipts (Section 80G)",
            reason=f"80G deduction of Rs {float(merged.section_80g):,.0f} claimed",
            status="recommended",
            priority="recommended",
        ))

    # ---- Section 80CCD(1B) NPS ----
    if merged.section_80ccd_1b > 0:
        items.append(ChecklistItem(
            document="NPS Contribution Statement (Section 80CCD(1B))",
            reason=f"80CCD(1B) deduction of Rs {float(merged.section_80ccd_1b):,.0f} claimed",
            status="recommended",
            priority="recommended",
        ))

    # ---- House property (home loan interest certificate) ----
    if merged.house_property_income != 0:
        items.append(ChecklistItem(
            document="Housing Loan Interest Certificate / Municipal Tax Receipts",
            reason=f"House property income of Rs {float(merged.house_property_income):,.0f}",
            status="recommended",
            priority="recommended",
        ))

    # ---- Business turnover → GST returns ----
    if merged.business_turnover > 0:
        items.append(ChecklistItem(
            document="GST Returns (GSTR-3B / GSTR-1) for the Financial Year",
            reason=f"Business turnover of Rs {float(merged.business_turnover):,.0f} declared",
            status="recommended",
            priority="recommended",
        ))
        items.append(ChecklistItem(
            document="Bank Statements (Business Account)",
            reason="Required for turnover reconciliation",
            status="recommended",
            priority="recommended",
        ))

    # ---- Advance tax challans ----
    if merged.advance_tax > 0:
        items.append(ChecklistItem(
            document="Advance Tax Challans (BSR Codes)",
            reason=f"Advance tax of Rs {float(merged.advance_tax):,.0f} paid",
            status="recommended",
            priority="required",
        ))

    # ---- Self-assessment tax challans ----
    if merged.self_assessment_tax > 0:
        items.append(ChecklistItem(
            document="Self-Assessment Tax Challans",
            reason=f"Self-assessment tax of Rs {float(merged.self_assessment_tax):,.0f} paid",
            status="recommended",
            priority="required",
        ))

    # Compute counts
    uploaded_count = sum(1 for i in items if i.status == "uploaded")
    missing_req = sum(1 for i in items if i.status == "missing" and i.priority == "required")
    missing_rec = sum(1 for i in items if i.status != "uploaded" and i.priority == "recommended")

    return DocumentChecklist(
        items=items,
        uploaded_count=uploaded_count,
        missing_required=missing_req,
        missing_recommended=missing_rec,
    )


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def format_checklist(checklist: DocumentChecklist, lang: str = "en") -> str:
    """Format a DocumentChecklist as WhatsApp-friendly text."""
    if not checklist.items:
        return "No documents required."

    lines: list[str] = ["--- Document Checklist ---", ""]

    for item in checklist.items:
        if item.status == "uploaded":
            icon = "[OK]"
        elif item.priority == "required":
            icon = "[MISSING]"
        else:
            icon = "[--]"

        lines.append(f"{icon} {item.document}")
        lines.append(f"    {item.reason}")

    lines.append("")
    lines.append(
        f"Uploaded: {checklist.uploaded_count} | "
        f"Missing (Required): {checklist.missing_required} | "
        f"Recommended: {checklist.missing_recommended}"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def checklist_to_dict(cl: DocumentChecklist) -> dict:
    """Serialize DocumentChecklist to a JSON-safe dict."""
    return {
        "items": [
            {
                "document": i.document,
                "reason": i.reason,
                "status": i.status,
                "priority": i.priority,
            }
            for i in cl.items
        ],
        "uploaded_count": cl.uploaded_count,
        "missing_required": cl.missing_required,
        "missing_recommended": cl.missing_recommended,
    }


def dict_to_checklist(data: dict) -> DocumentChecklist:
    """Deserialize a dict back to DocumentChecklist."""
    if not data:
        return DocumentChecklist()
    items = [
        ChecklistItem(
            document=i["document"],
            reason=i["reason"],
            status=i["status"],
            priority=i["priority"],
        )
        for i in data.get("items", [])
    ]
    return DocumentChecklist(
        items=items,
        uploaded_count=data.get("uploaded_count", 0),
        missing_required=data.get("missing_required", 0),
        missing_recommended=data.get("missing_recommended", 0),
    )
