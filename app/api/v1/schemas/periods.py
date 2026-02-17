# app/api/v1/schemas/periods.py
"""Pydantic schemas for GST return-period management (monthly compliance)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PeriodCreateRequest(BaseModel):
    """Request to create/get a return period."""
    gstin: str = Field(description="15-char GSTIN")
    period: str = Field(description="Period YYYY-MM, e.g. 2025-01")


class PeriodResponse(BaseModel):
    """Full return period detail."""
    id: str
    user_id: str
    gstin: str
    fy: str
    period: str
    status: str
    outward_count: int = 0
    inward_count: int = 0
    output_tax_igst: float = 0
    output_tax_cgst: float = 0
    output_tax_sgst: float = 0
    itc_igst: float = 0
    itc_cgst: float = 0
    itc_sgst: float = 0
    net_payable_igst: float = 0
    net_payable_cgst: float = 0
    net_payable_sgst: float = 0
    rcm_igst: float = 0
    rcm_cgst: float = 0
    rcm_sgst: float = 0
    risk_flags: str | None = None
    computed_at: str | None = None


class ReconciliationSummaryResponse(BaseModel):
    """Reconciliation summary for a period."""
    total_2b_entries: int = 0
    total_book_entries: int = 0
    matched: int = 0
    value_mismatch: int = 0
    missing_in_2b: int = 0
    missing_in_books: int = 0
    matched_taxable: float = 0
    mismatch_taxable_diff: float = 0


class LiabilityResponse(BaseModel):
    """Net liability computation result."""
    outward_count: int = 0
    inward_count: int = 0
    output_igst: float = 0
    output_cgst: float = 0
    output_sgst: float = 0
    itc_igst: float = 0
    itc_cgst: float = 0
    itc_sgst: float = 0
    net_igst: float = 0
    net_cgst: float = 0
    net_sgst: float = 0
    total_net_payable: float = 0
    rcm_igst: float = 0
    rcm_cgst: float = 0
    rcm_sgst: float = 0
    risk_flags: list[str] = []


class Import2bResponse(BaseModel):
    """Result of GSTR-2B import."""
    period: str = ""
    total_entries: int = 0
    supplier_count: int = 0
    total_taxable: float = 0
    errors: list[str] = []


class MismatchEntry(BaseModel):
    """A single ITC mismatch entry."""
    id: str
    supplier_gstin: str
    invoice_number: str
    taxable_value: float = 0
    match_status: str
    mismatch_details: str | None = None


class StatusTransitionRequest(BaseModel):
    """Request to transition period status."""
    new_status: str = Field(description="Target status")
