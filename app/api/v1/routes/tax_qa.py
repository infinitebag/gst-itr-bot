# app/api/v1/routes/tax_qa.py
"""
Tax Q&A and HSN/SAC lookup endpoints — powered by GPT-4o.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.infrastructure.db.models import User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok
from app.api.v1.schemas.tax_qa import (
    HsnLookupRequest,
    HsnLookupResponse,
    TaxQARequest,
    TaxQAResponse,
)

logger = logging.getLogger("api.v1.tax_qa")

router = APIRouter(tags=["Tax Q&A"])


@router.post("/tax-qa", response_model=dict)
async def tax_qa(
    body: TaxQARequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ask a tax-related question and get an AI-generated answer.

    RAG-enhanced: retrieves relevant knowledge from the knowledge base
    before answering. Falls back to vanilla GPT-4o if no relevant
    context is found.

    Supports multi-turn conversation via the optional ``history`` field.
    """
    from app.domain.services.rag_tax_qa import rag_tax_qa

    result = await rag_tax_qa(body.question, body.lang, body.history, db)

    return ok(
        data=TaxQAResponse(
            answer=result.answer,
            lang=body.lang,
            sources=result.sources if result.used_rag else None,
            used_rag=result.used_rag,
        ).model_dump(),
    )


@router.post("/hsn-lookup", response_model=dict)
async def hsn_lookup(body: HsnLookupRequest, user: User = Depends(get_current_user)):
    """
    Look up the HSN/SAC code for a product or service description.

    Uses GPT-4o to identify the correct code, GST rate, and category.
    """
    from app.infrastructure.external.openai_client import lookup_hsn

    result = await lookup_hsn(body.description, body.lang)

    resp = HsnLookupResponse(
        hsn_code=result.get("hsn_code"),
        sac_code=result.get("sac_code"),
        gst_rate=result.get("gst_rate") or result.get("rate"),
        category=result.get("category"),
        description=result.get("description"),
    )

    return ok(data=resp.model_dump())
