from datetime import date

from pydantic import BaseModel


class InvoiceData(BaseModel):
    id: str
    user_id: str
    invoice_date: date
    taxable_value: float
    tax_amount: float


class Gstr3bSummary(BaseModel):
    user_id: str
    period_start: date
    period_end: date
    total_taxable: float
    total_tax: float
    total_invoices: int
