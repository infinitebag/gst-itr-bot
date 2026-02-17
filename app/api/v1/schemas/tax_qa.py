# app/api/v1/schemas/tax_qa.py
"""Request and response schemas for tax Q&A and HSN lookup endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaxQARequest(BaseModel):
    question: str = Field(min_length=3, description="Tax-related question")
    lang: str = Field(default="en", description="Language code (en, hi, te, etc.)")
    history: list[dict] | None = Field(
        default=None,
        description="Optional conversation history for multi-turn Q&A",
    )


class TaxQAResponse(BaseModel):
    answer: str
    lang: str
    sources: list[dict] | None = Field(
        default=None,
        description="RAG source references (when knowledge base was used)",
    )
    used_rag: bool = Field(
        default=False,
        description="Whether the answer was enhanced with knowledge base context",
    )


class HsnLookupRequest(BaseModel):
    description: str = Field(
        min_length=2,
        description="Product or service description to look up HSN/SAC code",
    )
    lang: str = Field(default="en")


class HsnLookupResponse(BaseModel):
    hsn_code: str | None = None
    sac_code: str | None = None
    gst_rate: str | None = None
    category: str | None = None
    description: str | None = None
