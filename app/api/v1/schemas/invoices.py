# app/api/v1/schemas/invoices.py
"""Request and response schemas for invoice endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InvoiceCreate(BaseModel):
    """Manually create an invoice (all fields the user can set)."""

    invoice_number: str = Field(min_length=1, max_length=50)
    invoice_date: date | None = None

    supplier_gstin: str | None = Field(default=None, max_length=20)
    receiver_gstin: str | None = Field(default=None, max_length=20)
    recipient_gstin: str | None = Field(default=None, max_length=15)
    place_of_supply: str | None = Field(default=None, max_length=2)

    taxable_value: Decimal = Field(ge=0)
    total_amount: Decimal | None = Field(default=None, ge=0)
    tax_amount: Decimal = Field(ge=0)
    cgst_amount: Decimal | None = Field(default=None, ge=0)
    sgst_amount: Decimal | None = Field(default=None, ge=0)
    igst_amount: Decimal | None = Field(default=None, ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)


class InvoiceDetail(BaseModel):
    """Full invoice detail returned in responses."""

    id: str
    invoice_number: str
    invoice_date: date | None
    supplier_gstin: str | None
    receiver_gstin: str | None
    recipient_gstin: str | None
    place_of_supply: str | None

    taxable_value: Decimal
    total_amount: Decimal | None
    tax_amount: Decimal
    cgst_amount: Decimal | None
    sgst_amount: Decimal | None
    igst_amount: Decimal | None
    tax_rate: Decimal | None

    supplier_gstin_valid: bool | None
    receiver_gstin_valid: bool | None

    created_at: datetime

    class Config:
        from_attributes = True


class ParseTextRequest(BaseModel):
    """Parse raw OCR text into structured invoice fields."""

    text: str = Field(min_length=10, description="OCR text from an invoice image")
    save: bool = Field(
        default=False,
        description="If true, persist the parsed invoice to the database",
    )
    use_llm: bool = Field(
        default=False,
        description="If true, use GPT-4o for parsing instead of regex heuristics",
    )


class ParsedInvoiceResponse(BaseModel):
    """Structured fields extracted from invoice text."""

    supplier_gstin: str | None = None
    receiver_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    taxable_value: float | None = None
    total_amount: float | None = None
    tax_amount: float | None = None
    cgst_amount: float | None = None
    sgst_amount: float | None = None
    igst_amount: float | None = None
    place_of_supply: str | None = None
    tax_rate: float | None = None
    recipient_gstin: str | None = None
    supplier_gstin_valid: bool | None = None
    receiver_gstin_valid: bool | None = None

    # Only populated when save=true
    saved_invoice_id: str | None = None
