# app/api/v1/routes/invoices.py
"""
Invoice CRUD, OCR text parsing, and PDF download endpoints.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.infrastructure.db.models import Invoice, User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok, paginated
from app.api.v1.schemas.invoices import (
    InvoiceCreate,
    InvoiceDetail,
    ParseTextRequest,
    ParsedInvoiceResponse,
)

logger = logging.getLogger("api.v1.invoices")

router = APIRouter(prefix="/invoices", tags=["Invoices"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoice_to_detail(inv: Invoice) -> dict:
    """Convert an Invoice ORM object to InvoiceDetail dict."""
    return InvoiceDetail(
        id=str(inv.id),
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        supplier_gstin=inv.supplier_gstin,
        receiver_gstin=inv.receiver_gstin,
        recipient_gstin=inv.recipient_gstin,
        place_of_supply=inv.place_of_supply,
        taxable_value=inv.taxable_value,
        total_amount=inv.total_amount,
        tax_amount=inv.tax_amount,
        cgst_amount=inv.cgst_amount,
        sgst_amount=inv.sgst_amount,
        igst_amount=inv.igst_amount,
        tax_rate=inv.tax_rate,
        supplier_gstin_valid=inv.supplier_gstin_valid,
        receiver_gstin_valid=inv.receiver_gstin_valid,
        created_at=inv.created_at,
    ).model_dump()


# ---------------------------------------------------------------------------
# List invoices (paginated)
# ---------------------------------------------------------------------------

@router.get("", response_model=dict)
async def list_invoices(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    date_from: date | None = Query(default=None, description="Filter: invoice_date >= this"),
    date_to: date | None = Query(default=None, description="Filter: invoice_date <= this"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the authenticated user's invoices with optional date filters."""
    q = select(Invoice).where(Invoice.user_id == user.id)

    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)

    # Count
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch page
    q = q.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    invoices = result.scalars().all()

    return paginated(
        items=[_invoice_to_detail(inv) for inv in invoices],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Get single invoice
# ---------------------------------------------------------------------------

@router.get("/{invoice_id}", response_model=dict)
async def get_invoice(
    invoice_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single invoice owned by the authenticated user."""
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    return ok(data=_invoice_to_detail(inv))


# ---------------------------------------------------------------------------
# Create invoice manually
# ---------------------------------------------------------------------------

@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an invoice manually."""
    inv = Invoice(
        user_id=user.id,
        invoice_number=body.invoice_number,
        invoice_date=body.invoice_date,
        supplier_gstin=body.supplier_gstin,
        receiver_gstin=body.receiver_gstin,
        recipient_gstin=body.recipient_gstin,
        place_of_supply=body.place_of_supply,
        taxable_value=body.taxable_value,
        total_amount=body.total_amount,
        tax_amount=body.tax_amount,
        cgst_amount=body.cgst_amount,
        sgst_amount=body.sgst_amount,
        igst_amount=body.igst_amount,
        tax_rate=body.tax_rate,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)

    return ok(data=_invoice_to_detail(inv), message="Invoice created")


# ---------------------------------------------------------------------------
# Parse OCR text → structured invoice
# ---------------------------------------------------------------------------

@router.post("/parse-text", response_model=dict)
async def parse_text(
    body: ParseTextRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Parse raw OCR text into structured invoice fields.

    - ``use_llm=false`` (default): regex-based heuristic parser
    - ``use_llm=true``: GPT-4o powered extraction
    - ``save=true``: persist the parsed invoice to the database
    """
    if body.use_llm:
        from app.infrastructure.external.openai_client import parse_invoice_llm

        raw = await parse_invoice_llm(body.text)
        # parse_invoice_llm returns a dict; normalise keys
        parsed = ParsedInvoiceResponse(**{k: raw.get(k) for k in ParsedInvoiceResponse.model_fields})
    else:
        from app.domain.services.invoice_parser import parse_invoice_text

        result = parse_invoice_text(body.text)
        parsed = ParsedInvoiceResponse(
            supplier_gstin=result.supplier_gstin,
            receiver_gstin=result.receiver_gstin,
            invoice_number=result.invoice_number,
            invoice_date=str(result.invoice_date) if result.invoice_date else None,
            taxable_value=result.taxable_value,
            total_amount=result.total_amount,
            tax_amount=result.tax_amount,
            cgst_amount=result.cgst_amount,
            sgst_amount=result.sgst_amount,
            igst_amount=result.igst_amount,
            place_of_supply=result.place_of_supply,
            tax_rate=result.tax_rate,
            recipient_gstin=result.recipient_gstin,
            supplier_gstin_valid=result.supplier_gstin_valid,
            receiver_gstin_valid=result.receiver_gstin_valid,
        )

    # Optionally persist
    if body.save and parsed.invoice_number:
        inv = Invoice(
            user_id=user.id,
            invoice_number=parsed.invoice_number or "UNKNOWN",
            raw_text=body.text,
            supplier_gstin=parsed.supplier_gstin,
            receiver_gstin=parsed.receiver_gstin,
            recipient_gstin=parsed.recipient_gstin,
            place_of_supply=parsed.place_of_supply,
            taxable_value=parsed.taxable_value or 0,
            total_amount=parsed.total_amount,
            tax_amount=parsed.tax_amount or 0,
            cgst_amount=parsed.cgst_amount,
            sgst_amount=parsed.sgst_amount,
            igst_amount=parsed.igst_amount,
            tax_rate=parsed.tax_rate,
            supplier_gstin_valid=parsed.supplier_gstin_valid,
            receiver_gstin_valid=parsed.receiver_gstin_valid,
        )
        db.add(inv)
        await db.commit()
        await db.refresh(inv)
        parsed.saved_invoice_id = str(inv.id)

    return ok(data=parsed.model_dump())


# ---------------------------------------------------------------------------
# Download invoice PDF
# ---------------------------------------------------------------------------

@router.get("/{invoice_id}/pdf")
async def download_pdf(
    invoice_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a GST-compliant PDF for the invoice."""
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    from app.domain.services.invoice_pdf import generate_invoice_pdf

    invoice_data = {
        "invoice_number": inv.invoice_number,
        "invoice_date": str(inv.invoice_date) if inv.invoice_date else "",
        "supplier_gstin": inv.supplier_gstin or "",
        "receiver_gstin": inv.receiver_gstin or "",
        "recipient_gstin": inv.recipient_gstin or "",
        "place_of_supply": inv.place_of_supply or "",
        "taxable_value": float(inv.taxable_value),
        "total_amount": float(inv.total_amount) if inv.total_amount else 0,
        "tax_amount": float(inv.tax_amount),
        "cgst_amount": float(inv.cgst_amount) if inv.cgst_amount else 0,
        "sgst_amount": float(inv.sgst_amount) if inv.sgst_amount else 0,
        "igst_amount": float(inv.igst_amount) if inv.igst_amount else 0,
        "tax_rate": float(inv.tax_rate) if inv.tax_rate else 0,
    }

    pdf_bytes = generate_invoice_pdf(invoice_data)

    import io

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="invoice_{inv.invoice_number}.pdf"'
        },
    )
