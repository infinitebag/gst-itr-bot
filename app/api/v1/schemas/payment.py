# app/api/v1/schemas/payment.py
"""Pydantic schemas for payment tracking endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaymentCreateRequest(BaseModel):
    """Record a challan payment."""
    challan_number: str | None = None
    challan_date: str | None = Field(None, description="YYYY-MM-DD")
    igst: float = 0
    cgst: float = 0
    sgst: float = 0
    cess: float = 0
    total: float = 0
    payment_mode: str | None = Field(None, description="cash/neft/rtgs/online")
    bank_reference: str | None = None
    notes: str | None = None


class PaymentResponse(BaseModel):
    """Single payment record."""
    id: str
    period_id: str
    challan_number: str | None = None
    challan_date: str | None = None
    igst: float = 0
    cgst: float = 0
    sgst: float = 0
    cess: float = 0
    total: float = 0
    payment_mode: str | None = None
    bank_reference: str | None = None
    status: str = "pending"
    notes: str | None = None


class PaymentValidationResponse(BaseModel):
    """Payment validation result."""
    net_payable: dict = {}
    paid: dict = {}
    shortfall: dict = {}
    overpayment: float = 0
    is_fully_paid: bool = False
    payment_count: int = 0
