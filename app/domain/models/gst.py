from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class InvoiceData(BaseModel):
    id: str
    user_id: str
    invoice_date: date
    taxable_value: float
    tax_amount: float


class TaxBucket(BaseModel):
    taxable_value: Decimal = Field(default=Decimal("0"))
    igst: Decimal = Field(default=Decimal("0"))
    cgst: Decimal = Field(default=Decimal("0"))
    sgst: Decimal = Field(default=Decimal("0"))
    cess: Decimal = Field(default=Decimal("0"))


class ItcBucket(BaseModel):
    igst: Decimal = Field(default=Decimal("0"))
    cgst: Decimal = Field(default=Decimal("0"))
    sgst: Decimal = Field(default=Decimal("0"))
    cess: Decimal = Field(default=Decimal("0"))


class Gstr3bSummary(BaseModel):
    outward_taxable_supplies: TaxBucket = Field(default_factory=TaxBucket)
    inward_reverse_charge: TaxBucket = Field(default_factory=TaxBucket)
    itc_eligible: ItcBucket = Field(default_factory=ItcBucket)

    # Optional extra fields
    outward_nil_exempt: Decimal = Field(default=Decimal("0"))
    outward_non_gst: Decimal = Field(default=Decimal("0"))

    # Metadata (optional — for storage/display)
    user_id: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    total_taxable: Optional[float] = None
    total_tax: Optional[float] = None
    total_invoices: Optional[int] = None
