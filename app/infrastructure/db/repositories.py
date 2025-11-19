from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.infrastructure.db.models import Invoice
from app.domain.models.gst import InvoiceData

class InvoiceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_invoices_for_period(self, user_id: str, start: date, end: date):
        stmt = select(Invoice).where(
            Invoice.user_id == user_id,
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [
            InvoiceData(
                id=str(r.id),
                user_id=str(r.user_id),
                invoice_date=r.invoice_date,
                taxable_value=float(r.taxable_value),
                tax_amount=float(r.tax_amount),
            )
            for r in rows
        ]