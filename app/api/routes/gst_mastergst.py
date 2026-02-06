# app/api/routes/gst_mastergst.py

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.domain.services.gst_export import make_gstr1_json, make_gstr3b_json
from app.domain.services.gst_service import prepare_gstr3b
from app.domain.services.gstr1_service import prepare_gstr1_payload
from app.infrastructure.db.repositories import InvoiceRepository
from app.infrastructure.external.mastergst_client import MasterGSTClient

router = APIRouter()


def _parse_period(period: str) -> date:
    try:
        year_str, month_str = period.split("-")
        year = int(year_str)
        month = int(month_str)
        return date(year, month, 1)
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid period. Use YYYY-MM, e.g. 2025-11"
        )


@router.post("/gstr3b/file")
async def file_gstr3b_to_mastergst(
    user_id: int = Query(..., description="Internal user ID whose invoices to use"),
    period: str = Query(..., description="Return period YYYY-MM, e.g. 2025-11"),
    gstin: str | None = Query(None, description="GSTIN; defaults to GST_SANDBOX_GSTIN"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Build GSTR-3B JSON from saved invoices, then submit it to MasterGST sandbox.
    """

    if not settings.MASTERGST_API_KEY:
        raise HTTPException(
            status_code=500, detail="MASTERGST credentials not configured in settings"
        )

    period_start = _parse_period(period)
    from calendar import monthrange

    last_day = monthrange(period_start.year, period_start.month)[1]
    period_end = date(period_start.year, period_start.month, last_day)

    repo = InvoiceRepository(db)
    summary = await prepare_gstr3b(
        user_id=str(user_id),
        period_start=period_start,
        period_end=period_end,
        repo=repo,
    )

    if summary.total_invoices == 0:
        raise HTTPException(status_code=400, detail="No invoices found for that period")

    use_gstin = gstin or getattr(settings, "GST_SANDBOX_GSTIN", None) or "NA"
    gstr3b_json = make_gstr3b_json(use_gstin, period_start, summary)

    client = MasterGSTClient()
    resp = await client.submit_gstr3b(
        gstin=use_gstin,
        fp=gstr3b_json["fp"],
        payload=gstr3b_json,
    )

    return {
        "debug": {
            "user_id": user_id,
            "period": period,
            "gstin": use_gstin,
            "invoice_count": summary.total_invoices,
        },
        "request": gstr3b_json,
        "mastergst_response": resp,
    }


@router.post("/gstr1/file")
async def file_gstr1_to_mastergst(
    user_id: int = Query(..., description="Internal user ID whose invoices to use"),
    period: str = Query(..., description="Return period YYYY-MM, e.g. 2025-11"),
    gstin: str | None = Query(None, description="GSTIN; defaults to GST_SANDBOX_GSTIN"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Build GSTR-1 JSON from saved invoices, then submit it to MasterGST sandbox.
    """

    if not settings.MASTERGST_API_KEY:
        raise HTTPException(
            status_code=500, detail="MASTERGST credentials not configured in settings"
        )

    period_start = _parse_period(period)
    from calendar import monthrange

    last_day = monthrange(period_start.year, period_start.month)[1]
    period_end = date(period_start.year, period_start.month, last_day)

    repo = InvoiceRepository(db)
    use_gstin = gstin or getattr(settings, "GST_SANDBOX_GSTIN", None) or "NA"

    payload_obj = await prepare_gstr1_payload(
        user_id=str(user_id),
        gstin=use_gstin,
        period_start=period_start,
        period_end=period_end,
        repo=repo,
    )

    if not payload_obj.b2b and not payload_obj.b2c:
        raise HTTPException(status_code=400, detail="No invoices found for that period")

    gstr1_json = make_gstr1_json(payload_obj)

    client = MasterGSTClient()
    resp = await client.submit_gstr1(
        gstin=use_gstin,
        fp=gstr1_json["fp"],
        payload=gstr1_json,
    )

    b2b_invoices = sum(len(entry.inv) for entry in payload_obj.b2b)

    return {
        "debug": {
            "user_id": user_id,
            "period": period,
            "gstin": use_gstin,
            "b2b_parties": len(payload_obj.b2b),
            "b2b_invoices": b2b_invoices,
            "b2c_invoices": len(payload_obj.b2c),
        },
        "request": gstr1_json,
        "mastergst_response": resp,
    }
