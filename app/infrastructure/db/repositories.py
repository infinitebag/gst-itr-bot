# app/infrastructure/db/repositories.py

from collections.abc import Sequence
from datetime import date, datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services.invoice_parser import ParsedInvoice
from app.infrastructure.db.models import Invoice


class InvoiceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

        # ---------- READ: ALL INVOICES FOR A USER & PERIOD ----------

    async def get_invoices_for_period(
        self,
        user_id: int,
        period_start: date,
        period_end: date,
    ) -> list[Invoice]:
        """
        Return all invoices for a user where invoice_date is between period_start and period_end (inclusive).
        If invoice_date is null, we ignore it (you can change that if you want).
        """

        # Convert dates to datetimes in UTC for comparison
        start_dt = datetime(
            period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc
        )
        end_dt = datetime(
            period_end.year,
            period_end.month,
            period_end.day,
            23,
            59,
            59,
            tzinfo=timezone.utc,
        )

        stmt = (
            select(Invoice)
            .where(
                and_(
                    Invoice.user_id == user_id,
                    Invoice.invoice_date.isnot(None),
                    Invoice.invoice_date >= start_dt,
                    Invoice.invoice_date <= end_dt,
                )
            )
            .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_raw_invoices_for_period(
        self, user_id: str, start: date, end: date
    ) -> Sequence[Invoice]:
        """
        Raw SQLAlchemy Invoice rows for GSTR-1 (need more fields).
        """
        stmt = (
            select(Invoice)
            .where(
                Invoice.user_id == user_id,
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
            .order_by(Invoice.invoice_date, Invoice.invoice_number)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # ---------- CREATE FROM PARSED OCR ----------
    async def create_from_parsed(
        self,
        user_id: int,
        parsed: ParsedInvoice,
        raw_text: str,
    ) -> Invoice:
        inv = Invoice(
            user_id=user_id,
            raw_text=raw_text,
            supplier_gstin=parsed.supplier_gstin,
            receiver_gstin=parsed.receiver_gstin,
            invoice_number=parsed.invoice_number,
            invoice_date=parsed.invoice_date,
            taxable_value=parsed.taxable_value,
            total_amount=parsed.total_amount,
            tax_amount=parsed.tax_amount,
            cgst_amount=parsed.cgst_amount,
            sgst_amount=parsed.sgst_amount,
            igst_amount=parsed.igst_amount,
            place_of_supply=parsed.place_of_supply,
            supplier_gstin_valid=parsed.supplier_gstin_valid,
            receiver_gstin_valid=parsed.receiver_gstin_valid,
        )
        self.db.add(inv)
        await self.db.commit()
        await self.db.refresh(inv)
        return inv
