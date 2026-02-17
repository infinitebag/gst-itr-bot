from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token
from app.core.db import get_db
from app.infrastructure.db.models import Invoice, User

router = APIRouter(prefix="/admin/invoices", tags=["admin-invoices"])


@router.get("/{invoice_id}/summary.pdf")
async def invoice_summary_pdf(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    stmt = select(Invoice).where(Invoice.id == invoice_id)
    result = await db.execute(stmt)
    inv: Invoice | None = result.scalar_one_or_none()

    if inv is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    user_stmt = select(User).where(User.id == inv.user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    def line(text: str, step: int = 16):
        nonlocal y
        p.drawString(50, y, text)
        y -= step

    p.setFont("Helvetica-Bold", 16)
    line("Invoice Summary", step=24)

    p.setFont("Helvetica", 11)
    line(f"Invoice ID: {inv.id}")
    line(f"Invoice Number: {inv.invoice_number or '-'}")
    if inv.invoice_date:
        line(f"Invoice Date: {inv.invoice_date.isoformat()}")
    if user:
        line(f"Customer WhatsApp: {user.whatsapp_number}")

    line("")
    line(f"Supplier GSTIN: {inv.supplier_gstin or '-'}")
    line(f"Receiver GSTIN: {inv.receiver_gstin or '-'}")
    line(f"Place of Supply: {inv.place_of_supply or '-'}")

    def fmt(v):
        return f"₹{float(v):,.2f}" if v is not None else "-"

    line("")
    line(f"Taxable Value: {fmt(inv.taxable_value)}")
    line(f"CGST: {fmt(inv.cgst_amount)}")
    line(f"SGST: {fmt(inv.sgst_amount)}")
    line(f"IGST: {fmt(inv.igst_amount)}")
    line(f"Total Tax: {fmt(inv.tax_amount)}")
    line(f"Invoice Total: {fmt(inv.total_amount)}")

    p.showPage()
    p.save()
    buffer.seek(0)

    filename = f"invoice_{inv.id}_summary.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
