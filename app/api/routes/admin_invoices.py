
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.schemas_admin import InvoiceCreate, InvoiceOut
from app.core.config import settings
from app.core.db import get_db
from app.infrastructure.db.models import User
from app.infrastructure.db.repositories import InvoiceRepository

router = APIRouter(prefix="/admin", tags=["admin"])


async def verify_admin_key(x_admin_key: str = Header(None)):
    """
    Very simple header-based admin auth.
    In production, replace with proper auth (JWT / OAuth / etc.).
    """
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_API_KEY not configured on server.",
        )
    if x_admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key.",
        )
    return True


@router.post(
    "/invoices", response_model=InvoiceOut, dependencies=[Depends(verify_admin_key)]
)
async def create_invoice(
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
):
    # Ensure user exists (same WhatsApp number format used in bot)
    result = await db.execute(
        select(User).where(User.whatsapp_number == payload.whatsapp_number)
    )
    user = result.scalar_one_or_none()
    if user is None:
        # Auto-create user, so you can seed invoices before first chat
        user = User(whatsapp_number=payload.whatsapp_number)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    repo = InvoiceRepository(db)
    invoice = await repo.create_invoice_for_user(
        user=user,
        invoice_date=payload.invoice_date,
        taxable_value=payload.taxable_value,
        tax_amount=payload.tax_amount,
    )

    return InvoiceOut(
        id=invoice.id,
        whatsapp_number=payload.whatsapp_number,
        invoice_date=invoice.invoice_date,
        taxable_value=invoice.taxable_value,
        tax_amount=invoice.tax_amount,
    )


@router.get(
    "/invoices/{whatsapp_number}",
    response_model=list[InvoiceOut],
    dependencies=[Depends(verify_admin_key)],
)
async def list_invoices(
    whatsapp_number: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.whatsapp_number == whatsapp_number)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return []

    repo = InvoiceRepository(db)
    invoices = await repo.list_invoices_for_user(user)

    return [
        InvoiceOut(
            id=inv.id,
            whatsapp_number=whatsapp_number,
            invoice_date=inv.invoice_date,
            taxable_value=inv.taxable_value,
            tax_amount=inv.tax_amount,
        )
        for inv in invoices
    ]
