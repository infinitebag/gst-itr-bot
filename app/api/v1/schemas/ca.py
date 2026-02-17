# app/api/v1/schemas/ca.py
"""Request and response schemas for CA authentication, client management,
reviews, analytics, and admin CA operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# CA Auth
# ---------------------------------------------------------------------------

class CALoginRequest(BaseModel):
    email: EmailStr
    password: str


class CARegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = None
    membership_number: str | None = Field(
        default=None,
        description="ICAI membership number",
    )


class CATokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class CARefreshRequest(BaseModel):
    refresh_token: str


class CAProfile(BaseModel):
    id: int
    email: str
    name: str
    phone: str | None = None
    membership_number: str | None = None
    active: bool
    approved: bool
    created_at: datetime | None = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Business Client
# ---------------------------------------------------------------------------

class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    whatsapp_number: str | None = None
    gstin: str | None = None
    pan: str | None = None
    email: EmailStr | None = None
    business_type: str | None = Field(
        default=None,
        description="One of: sole_prop, partnership, pvt_ltd, llp, public_ltd, trust, huf",
    )
    address: str | None = None
    state_code: str | None = Field(default=None, max_length=2)
    notes: str | None = None
    # Segment fields (Phase 4)
    segment: str | None = Field(default=None, description="small / medium / enterprise")
    annual_turnover: float | None = None
    monthly_invoice_volume: int | None = None


class ClientUpdate(BaseModel):
    """All fields optional for partial update."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    whatsapp_number: str | None = None
    gstin: str | None = None
    pan: str | None = None
    email: EmailStr | None = None
    business_type: str | None = None
    address: str | None = None
    state_code: str | None = Field(default=None, max_length=2)
    notes: str | None = None
    # Segment fields (Phase 4)
    segment: str | None = Field(default=None, description="small / medium / enterprise")
    annual_turnover: float | None = None
    monthly_invoice_volume: int | None = None


class ClientOut(BaseModel):
    id: int
    name: str
    gstin: str | None = None
    pan: str | None = None
    whatsapp_number: str | None = None
    email: str | None = None
    business_type: str | None = None
    address: str | None = None
    state_code: str | None = None
    notes: str | None = None
    status: str
    ca_id: int
    # Segment fields (Phase 4)
    segment: str = "small"
    annual_turnover: float | None = None
    monthly_invoice_volume: int | None = None
    gstin_count: int = 1
    is_exporter: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class BulkUploadRow(BaseModel):
    row: int
    name: str
    reason: str | None = None
    client_id: int | None = None


class BulkUploadResult(BaseModel):
    added_count: int
    skipped_count: int
    failed_count: int
    added: list[BulkUploadRow]
    skipped: list[BulkUploadRow]
    failed: list[BulkUploadRow]


# ---------------------------------------------------------------------------
# ITR Review
# ---------------------------------------------------------------------------

class ITRReviewOut(BaseModel):
    id: str
    form_type: str | None = None
    assessment_year: str | None = None
    pan: str | None = None
    status: str | None = None
    ca_notes: str | None = None
    ca_reviewed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    recommended_regime: str | None = None
    tax_payable: float | None = None
    savings: float | None = None
    input_data: dict[str, Any] | None = None
    result_data: dict[str, Any] | None = None
    merged_data: dict[str, Any] | None = None
    mismatch_data: dict[str, Any] | None = None
    checklist_data: dict[str, Any] | None = None
    linked_gst_filing_ids: list[str] = Field(default_factory=list)
    allowed_transitions: list[str] = Field(default_factory=list)


class ReviewAction(BaseModel):
    ca_notes: str | None = Field(default=None, description="Notes from the CA")


class ITREditRequest(BaseModel):
    """Fields to edit on an ITR draft — recomputes the tax."""
    input_overrides: dict[str, Any] = Field(
        description="Key-value pairs to override in the ITR input data",
    )
    ca_notes: str | None = None


# ---------------------------------------------------------------------------
# GST Review
# ---------------------------------------------------------------------------

class GSTReviewOut(BaseModel):
    id: str
    filing_type: str | None = None
    form_type: str | None = None
    gstin: str | None = None
    period: str | None = None
    status: str | None = None
    ca_notes: str | None = None
    ca_reviewed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    reference_number: str | None = None
    is_nil: bool = False
    invoice_count: int = 0
    total_taxable: float = 0.0
    total_tax: float = 0.0
    invoices: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] | None = None
    response_data: dict[str, Any] | None = None
    allowed_transitions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class AnalyticsOut(BaseModel):
    summary: dict[str, Any]
    anomalies: list[dict[str, Any]]
    deadlines: list[dict[str, Any]]


class InsightsOut(BaseModel):
    text: str
    generated_at: datetime


# ---------------------------------------------------------------------------
# Admin CA Management
# ---------------------------------------------------------------------------

class AdminCAOut(BaseModel):
    id: int
    email: str
    name: str
    phone: str | None = None
    membership_number: str | None = None
    active: bool
    approved: bool
    approved_at: datetime | None = None
    created_at: datetime | None = None
    last_login: datetime | None = None
    client_count: int = 0
    pending_gst_count: int = 0
    pending_itr_count: int = 0


class TransferRequest(BaseModel):
    new_ca_id: int = Field(description="ID of the target CA to transfer the client to")


# ---------------------------------------------------------------------------
# Unassigned Filing Queue
# ---------------------------------------------------------------------------

class AssignCARequest(BaseModel):
    """Request body for assigning a CA to an unassigned filing."""
    ca_id: int = Field(description="ID of the CA to assign")
    create_business_client: bool = Field(
        default=False,
        description="If True, also create a BusinessClient record to auto-route future filings",
    )


class UnassignedGSTItem(BaseModel):
    """A GST filing in the unassigned queue."""
    id: str
    filing_type: str = "GST"
    form_type: str | None = None
    gstin: str | None = None
    period: str | None = None
    status: str
    user_id: str
    user_whatsapp: str | None = None
    user_name: str | None = None
    created_at: datetime | None = None
    is_nil: bool = False


class UnassignedITRItem(BaseModel):
    """An ITR draft in the unassigned queue."""
    id: str
    form_type: str | None = None
    assessment_year: str | None = None
    pan: str | None = None
    status: str
    user_id: str
    user_whatsapp: str | None = None
    user_name: str | None = None
    created_at: datetime | None = None


class UnassignedQueueOut(BaseModel):
    """Combined unassigned queue for both GST and ITR."""
    gst_filings: list[UnassignedGSTItem] = Field(default_factory=list)
    itr_drafts: list[UnassignedITRItem] = Field(default_factory=list)
    gst_total: int = 0
    itr_total: int = 0
