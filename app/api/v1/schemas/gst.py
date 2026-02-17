# app/api/v1/schemas/gst.py
"""Request and response schemas for GST endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# GSTR-3B
# ---------------------------------------------------------------------------

class TaxBucketSchema(BaseModel):
    taxable_value: Decimal = Decimal("0")
    igst: Decimal = Decimal("0")
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    cess: Decimal = Decimal("0")


class ItcBucketSchema(BaseModel):
    igst: Decimal = Decimal("0")
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    cess: Decimal = Decimal("0")


class Gstr3bResponse(BaseModel):
    outward_taxable_supplies: TaxBucketSchema
    inward_reverse_charge: TaxBucketSchema
    itc_eligible: ItcBucketSchema
    outward_nil_exempt: Decimal = Decimal("0")
    outward_non_gst: Decimal = Decimal("0")


class Gstr3bRequest(BaseModel):
    """
    Optional request body for GSTR-3B preparation.

    If ``period`` is omitted the current period is used.
    If ``demo`` is true, sample data is returned.
    """

    period: str | None = Field(
        default=None,
        description="GST return period YYYY-MM (defaults to current)",
    )
    demo: bool = Field(default=False, description="Return demo/sample data")


# ---------------------------------------------------------------------------
# NIL Filing
# ---------------------------------------------------------------------------

class NilFilingRequest(BaseModel):
    gstin: str = Field(min_length=15, max_length=15, description="15-character GSTIN")
    period: str = Field(description="Return period YYYY-MM")
    form_type: str = Field(
        default="gstr3b",
        description="Form type: gstr3b or gstr1",
    )


class NilFilingResponse(BaseModel):
    form_type: str
    gstin: str
    period: str
    status: str
    reference_number: str
    message: str
    filed_at: str


# ---------------------------------------------------------------------------
# Current Period
# ---------------------------------------------------------------------------

class CurrentPeriodResponse(BaseModel):
    period: str = Field(description="Current GST period (YYYY-MM)")
