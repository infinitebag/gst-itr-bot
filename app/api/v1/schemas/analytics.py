# app/api/v1/schemas/analytics.py
"""Request and response schemas for analytics endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class TaxSummarySchema(BaseModel):
    period_start: date
    period_end: date
    total_invoices: int
    total_taxable_value: Decimal
    total_tax: Decimal
    total_cgst: Decimal
    total_sgst: Decimal
    total_igst: Decimal
    total_amount: Decimal
    b2b_count: int
    b2c_count: int
    unique_suppliers: int
    unique_receivers: int
    avg_invoice_value: Decimal
    tax_rate_distribution: dict


class AnomalySchema(BaseModel):
    duplicate_invoice_numbers: list[dict]
    invalid_gstins: list[dict]
    high_value_invoices: list[dict]
    missing_fields: list[dict]
    tax_rate_outliers: list[dict]
    total_anomalies: int


class DeadlineSchema(BaseModel):
    form_name: str
    due_date: date
    period: str
    days_remaining: int
    status: str
    description: str = ""


class InsightsRequest(BaseModel):
    lang: str = Field(default="en", description="Language code (en, hi, te, etc.)")


class InsightsResponse(BaseModel):
    insights: str = Field(description="AI-generated tax insights text")
