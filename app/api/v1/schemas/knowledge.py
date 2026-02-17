# app/api/v1/schemas/knowledge.py
"""Request and response schemas for Knowledge Base (RAG) endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Ingest ─────────────────────────────────────────────────────────


class KnowledgeIngestRequest(BaseModel):
    title: str = Field(min_length=3, description="Document title")
    content: str = Field(min_length=10, description="Full document text")
    category: str = Field(
        description="Category: gst, itr, general, ca_precedent, circular"
    )
    source: str | None = Field(
        default=None,
        description="Source URL, circular number, or reference",
    )
    effective_date: date | None = Field(
        default=None,
        description="Date the document/rule became effective",
    )
    metadata: dict | None = Field(
        default=None,
        description="Extra metadata (section numbers, act, etc.)",
    )


class KnowledgeIngestResponse(BaseModel):
    document_id: str
    title: str
    chunk_count: int
    category: str


# ── Search ─────────────────────────────────────────────────────────


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=3, description="Search query text")
    category: str | None = Field(default=None, description="Filter by category")
    top_k: int = Field(default=5, ge=1, le=20, description="Max results")
    threshold: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description="Minimum similarity threshold",
    )


class KnowledgeSearchResult(BaseModel):
    chunk_content: str
    section_header: str | None = None
    similarity: float
    document_title: str
    category: str
    source: str | None = None
    document_id: str


# ── Document listing ───────────────────────────────────────────────


class KnowledgeDocumentResponse(BaseModel):
    id: str
    title: str
    category: str
    source: str | None = None
    chunk_count: int
    is_active: bool
    effective_date: date | None = None
    created_at: str | None = None
