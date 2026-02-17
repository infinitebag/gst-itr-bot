# app/api/v1/schemas/risk.py
"""Pydantic schemas for risk scoring endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskFlagEntry(BaseModel):
    code: str
    severity: str
    points: int = 0
    evidence: str = ""


class RecommendedActionEntry(BaseModel):
    action: str
    why: str


class RiskAssessmentResponse(BaseModel):
    """Full risk assessment detail."""
    id: str
    period_id: str
    risk_score: int = 0
    risk_level: str = "LOW"
    risk_flags: list[RiskFlagEntry] = []
    recommended_actions: list[RecommendedActionEntry] = []
    category_a_score: int = 0
    category_b_score: int = 0
    category_c_score: int = 0
    category_d_score: int = 0
    category_e_score: int = 0
    ca_override_score: int | None = None
    ca_override_notes: str | None = None
    ca_final_outcome: str | None = None
    post_filing_outcome: str | None = None
    computed_at: str | None = None


class CAOverrideRequest(BaseModel):
    """CA override for risk score."""
    override_score: int = Field(ge=0, le=100, description="Manual override score (0-100)")
    notes: str | None = None


class OutcomeRecordRequest(BaseModel):
    """Record CA and post-filing outcomes."""
    ca_outcome: str | None = Field(None, description="approved/approved_with_changes/major_changes")
    filing_outcome: str | None = Field(None, description="clean/notice/query/late_fee")
