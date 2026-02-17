import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services.invoice_parser import ParsedInvoice
from app.infrastructure.db.models import Invoice


class InvoiceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---------- small helpers ----------

    @staticmethod
    def _to_decimal(value, default: str = "0.00") -> Decimal:
        """
        Safely convert incoming float/str/Decimal/None to Decimal.
        """
        if value is None:
            return Decimal(default)

        if isinstance(value, Decimal):
            return value

        try:
            # Handles int / float / str
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    @staticmethod
    def _normalize_pos(raw: str | None) -> str | None:
        """
        Normalize place_of_supply into 2-digit state code,
        so it always fits VARCHAR(2).
        """
        if not raw:
            return None

        raw = raw.strip()
        if not raw:
            return None

        # Try to find a standalone 2-digit number first, e.g. "Andhra Pradesh (37)"
        m = re.search(r"\b(\d{2})\b", raw)
        if m:
            return m.group(1)

        # Fallback: first 2 characters (e.g. "37", "GJ", "DL")
        return raw[:2]

    # ---------- main methods ----------

    async def create_from_parsed(
        self,
        user_id: uuid.UUID,
        parsed: ParsedInvoice,
        raw_text: str | None = None,
        *,
        direction: str = "outward",
        itc_eligible: bool = False,
        reverse_charge: bool = False,
    ) -> Invoice:
        """
        Create an Invoice row from ParsedInvoice, making sure:

        - place_of_supply is max 2 chars,
        - taxable_value and tax_amount are NEVER NULL (use Decimal),
        - total_amount is consistent.
        """
        # --- Place of supply -> 2-char code ---
        pos_code = self._normalize_pos(parsed.place_of_supply)

        # --- Convert all numeric fields to Decimal safely ---
        total = (
            self._to_decimal(parsed.total_amount, default="0.00")
            if parsed.total_amount is not None
            else None
        )
        taxable = (
            self._to_decimal(parsed.taxable_value, default="0.00")
            if parsed.taxable_value is not None
            else None
        )
        tax_amt = (
            self._to_decimal(parsed.tax_amount, default="0.00")
            if parsed.tax_amount is not None
            else None
        )
        rate = (
            self._to_decimal(parsed.tax_rate, default="0.00")
            if parsed.tax_rate is not None
            else None
        )

        # If rate is 0 or effectively 0, treat as no rate
        if rate is not None and rate <= Decimal("0"):
            rate = None

        # ---------- 1) Ensure taxable_value (NOT NULL) ----------
        if taxable is None:
            if total is not None and tax_amt is not None:
                # total = taxable + tax
                taxable = total - tax_amt
            elif total is not None and rate is not None:
                # assume total is tax-inclusive
                taxable = (total * Decimal("100")) / (Decimal("100") + rate)
            elif tax_amt is not None and rate is not None:
                # tax = taxable * rate/100  ⇒  taxable = tax*100/rate
                taxable = (tax_amt * Decimal("100")) / rate
            else:
                taxable = Decimal("0.00")

        # Guard against weird negative
        if taxable < 0:
            taxable = Decimal("0.00")

        # ---------- 2) Ensure tax_amount (NOT NULL) ----------
        if tax_amt is None:
            if total is not None and taxable is not None:
                tax_amt = total - taxable
            elif taxable is not None and rate is not None:
                tax_amt = (taxable * rate) / Decimal("100")
            elif total is not None and rate is not None:
                # assume total is tax-inclusive
                tax_amt = (total * rate) / (Decimal("100") + rate)
            else:
                tax_amt = Decimal("0.00")

        if tax_amt < 0:
            tax_amt = Decimal("0.00")

        # ---------- 3) Ensure total_amount (can be NULL, but we prefer consistency) ----------
        if total is None:
            total = taxable + tax_amt

        # ---------- Final invoice row ----------
        invoice = Invoice(
            id=uuid.uuid4(),
            user_id=user_id,
            raw_text=raw_text,
            supplier_gstin=parsed.supplier_gstin,
            receiver_gstin=parsed.receiver_gstin,
            invoice_number=parsed.invoice_number,
            invoice_date=parsed.invoice_date,
            recipient_gstin=parsed.recipient_gstin,
            place_of_supply=pos_code,  # fits VARCHAR(2)
            taxable_value=taxable,  # NOT NULL
            total_amount=total,  # consistent total
            tax_amount=tax_amt,  # NOT NULL
            cgst_amount=(
                self._to_decimal(parsed.cgst_amount)
                if parsed.cgst_amount is not None
                else None
            ),
            sgst_amount=(
                self._to_decimal(parsed.sgst_amount)
                if parsed.sgst_amount is not None
                else None
            ),
            igst_amount=(
                self._to_decimal(parsed.igst_amount)
                if parsed.igst_amount is not None
                else None
            ),
            tax_rate=rate if rate is not None else None,
            supplier_gstin_valid=parsed.supplier_gstin_valid,
            receiver_gstin_valid=parsed.receiver_gstin_valid,
            direction=direction,
            itc_eligible=itc_eligible,
            reverse_charge=reverse_charge,
        )

        self.db.add(invoice)
        await self.db.commit()
        await self.db.refresh(invoice)
        return invoice

    async def list_for_period(
        self,
        user_id: uuid.UUID,
        start: date,
        end: date,
    ) -> list[Invoice]:
        """
        Return all invoices for a user with invoice_date in [start, end].
        Used by GSTR-1 and GSTR-3B preparation.
        """
        stmt = (
            select(Invoice)
            .where(
                and_(
                    Invoice.user_id == user_id,
                    Invoice.invoice_date >= start,
                    Invoice.invoice_date <= end,
                )
            )
            .order_by(Invoice.invoice_date, Invoice.created_at)
        )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
    ) -> list[Invoice]:
        """
        Handy helper – show last N invoices for quick WhatsApp queries.
        """
        stmt = (
            select(Invoice)
            .where(Invoice.user_id == user_id)
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ---------- monthly compliance helpers ----------

    async def list_for_period_by_direction(
        self,
        user_id: uuid.UUID,
        start: date,
        end: date,
        direction: str,
    ) -> list[Invoice]:
        """Return invoices filtered by direction ('outward' or 'inward')."""
        stmt = (
            select(Invoice)
            .where(
                and_(
                    Invoice.user_id == user_id,
                    Invoice.invoice_date >= start,
                    Invoice.invoice_date <= end,
                    Invoice.direction == direction,
                )
            )
            .order_by(Invoice.invoice_date, Invoice.created_at)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_match_status(
        self,
        invoice_id: uuid.UUID,
        match_status: str,
        match_id: uuid.UUID | None = None,
    ) -> Invoice | None:
        """Update gstr2b_match_status and gstr2b_match_id after reconciliation."""
        stmt = select(Invoice).where(Invoice.id == invoice_id)
        result = await self.db.execute(stmt)
        invoice = result.scalar_one_or_none()
        if not invoice:
            return None

        invoice.gstr2b_match_status = match_status
        if match_id:
            invoice.gstr2b_match_id = match_id
        await self.db.commit()
        await self.db.refresh(invoice)
        return invoice
