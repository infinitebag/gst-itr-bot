# app/api/routes/gst_gstr1_debug.py

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.domain.services.gstr1_service import prepare_gstr1_payload
from app.infrastructure.db.repositories import InvoiceRepository

router = APIRouter(prefix="/debug/gst", tags=["GST Debug"])


@router.get("/gstr1/preview")
async def preview_gstr1(
    user_id: str = Query(..., description="User UUID string"),
    period_start: date = Query(..., description="Start date, e.g. 2025-11-01"),
    period_end: date = Query(..., description="End date, e.g. 2025-11-30"),
    db: AsyncSession = Depends(get_db),
):
    """
    Preview GSTR-1 JSON payload (B2B + B2C) for a given user and period.

    Example:
    GET /debug/gst/gstr1/preview?user_id=...&period_start=2025-11-01&period_end=2025-11-30
    """
    repo = InvoiceRepository(db)
    payload = await prepare_gstr1_payload(
        user_id=user_id,
        gstin=getattr(settings, "GST_SANDBOX_GSTIN", None) or "NA",
        period_start=period_start,
        period_end=period_end,
        repo=repo,
    )
    return payload
