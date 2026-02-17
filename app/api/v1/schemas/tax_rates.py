# app/api/v1/schemas/tax_rates.py
"""Pydantic schemas for tax rate administration endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaxRateConfigOut(BaseModel):
    """Response schema for a stored tax rate configuration version."""

    id: str
    rate_type: str
    assessment_year: str | None = None
    config: dict[str, Any]
    source: str
    version: int
    is_active: bool
    created_by: str | None = None
    notes: str | None = None
    created_at: datetime | None = None


class ITRSlabOverride(BaseModel):
    """Request body for manually overriding ITR slabs."""

    assessment_year: str = Field(default="2025-26", pattern=r"^\d{4}-\d{2}$")
    config: dict[str, Any] = Field(
        description="Full ITRSlabConfig as JSON dict "
        "(old_regime_slabs, new_regime_slabs, rebate_87a_*, section_80c_max, etc.)",
    )
    notes: str | None = None


class GSTRateOverride(BaseModel):
    """Request body for manually overriding GST rates."""

    valid_rates: list[float] = Field(description="List of valid GST rate percentages")
    notes: str | None = None


class RefreshRequest(BaseModel):
    """Request body for triggering an OpenAI rate refresh."""

    assessment_year: str = Field(default="2025-26", pattern=r"^\d{4}-\d{2}$")
