from datetime import date

from pydantic import BaseModel, Field


class InvoiceCreate(BaseModel):
    whatsapp_number: str = Field(..., example="919876543210")
    invoice_date: date = Field(..., example="2025-11-01")
    taxable_value: float = Field(..., gt=0, example=10000.0)
    tax_amount: float = Field(..., ge=0, example=1800.0)


class InvoiceOut(BaseModel):
    id: str
    whatsapp_number: str
    invoice_date: date
    taxable_value: float
    tax_amount: float
