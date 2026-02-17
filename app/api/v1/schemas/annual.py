# app/api/v1/schemas/annual.py
"""Pydantic schemas for annual return (GSTR-9) endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnnualCreateRequest(BaseModel):
    """Create/get annual return."""
    gstin: str = Field(description="15-char GSTIN")
    fy: str = Field(description="Financial year e.g. 2024-25")


class AnnualReturnResponse(BaseModel):
    """Annual return detail."""
    id: str
    user_id: str
    gstin: str
    fy: str
    status: str = "draft"
    total_outward_taxable: float = 0
    total_inward_taxable: float = 0
    total_itc_claimed: float = 0
    total_itc_reversed: float = 0
    total_tax_paid: float = 0
    risk_score: int | None = None
    computed_at: str | None = None


class AnnualStatusTransitionRequest(BaseModel):
    """Transition annual return status."""
    new_status: str = Field(description="Target status")
