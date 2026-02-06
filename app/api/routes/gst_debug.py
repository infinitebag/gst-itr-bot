# app/api/routes/gst_debug.py

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.domain.services.gst_export import make_gstr1_json, make_gstr3b_json
from app.domain.services.gst_sandbox import submit_gstr3b_to_sandbox
from app.domain.services.gst_service import prepare_gstr3b
from app.domain.services.gstr1_service import prepare_gstr1_payload
from app.infrastructure.db.repositories import InvoiceRepository

router = APIRouter()


def _parse_period(period: str) -> date:
    """
    Parse 'YYYY-MM' into a date pointing to the first day of the month.
    """
    try:
        year_str, month_str = period.split("-")
        year = int(year_str)
        month = int(month_str)
        return date(year, month, 1)
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid period format. Use YYYY-MM, e.g. 2025-11."
        )


@router.get("/gstr3b-json")
async def get_gstr3b_json(
    user_id: int = Query(..., description="Internal user ID"),
    period: str = Query(
        ..., description="Return period in YYYY-MM format, e.g. 2025-11"
    ),
    gstin: str | None = Query(
        None, description="GSTIN to use in JSON. Defaults to GST_SANDBOX_GSTIN"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Debug endpoint:
    - Reads invoices from DB for the user + period
    - Builds GSTR-3B summary
    - Returns a sandbox-style JSON payload
    """
    period_start = _parse_period(period)
    # end-of-month:
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

    use_gstin = gstin or getattr(settings, "GST_SANDBOX_GSTIN", None) or "NA"
    payload = make_gstr3b_json(use_gstin, period_start, summary)

    return {
        "debug": {
            "user_id": user_id,
            "period": period,
            "invoice_count": summary.total_invoices,
        },
        "gstr3b_json": payload,
    }


@router.get("/gstr1-json")
async def get_gstr1_json(
    user_id: int = Query(..., description="Internal user ID"),
    period: str = Query(
        ..., description="Return period in YYYY-MM format, e.g. 2025-11"
    ),
    gstin: str | None = Query(
        None, description="GSTIN to use in JSON. Defaults to GST_SANDBOX_GSTIN"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Debug endpoint:
    - Reads invoices from DB for the user + period
    - Builds internal GSTR-1 payload (b2b/b2c)
    - Exports a sandbox-style JSON payload
    """
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

    payload_json = make_gstr1_json(payload_obj)

    # Some quick debug stats
    b2b_count = len(payload_obj.b2b)
    b2b_invoice_count = sum(len(entry.inv) for entry in payload_obj.b2b)
    b2c_invoice_count = len(payload_obj.b2c)

    return {
        "debug": {
            "user_id": user_id,
            "period": period,
            "b2b_parties": b2b_count,
            "b2b_invoices": b2b_invoice_count,
            "b2c_invoices": b2c_invoice_count,
        },
        "gstr1_json": payload_json,
    }


@router.get("/invoices")
async def list_invoices(
    user_id: int = Query(..., description="Internal user ID"),
    period: str = Query(
        ..., description="Return period in YYYY-MM format, e.g. 2025-11"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Debug endpoint:
    - Lists all invoices for a user + period
    - Shows key fields so you can understand what the OCR + parser is doing
    """
    period_start = _parse_period(period)
    from calendar import monthrange

    last_day = monthrange(period_start.year, period_start.month)[1]
    period_end = date(period_start.year, period_start.month, last_day)

    repo = InvoiceRepository(db)
    invoices = await repo.get_invoices_for_period(
        user_id=user_id,
        period_start=period_start,
        period_end=period_end,
    )

    items: list[dict[str, Any]] = []
    for inv in invoices:
        items.append(
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "invoice_date": (
                    inv.invoice_date.isoformat() if inv.invoice_date else None
                ),
                "supplier_gstin": inv.supplier_gstin,
                "receiver_gstin": inv.receiver_gstin,
                "place_of_supply": inv.place_of_supply,
                "taxable_value": (
                    float(inv.taxable_value) if inv.taxable_value is not None else None
                ),
                "total_amount": (
                    float(inv.total_amount) if inv.total_amount is not None else None
                ),
                "tax_amount": (
                    float(inv.tax_amount) if inv.tax_amount is not None else None
                ),
                "cgst_amount": (
                    float(inv.cgst_amount) if inv.cgst_amount is not None else None
                ),
                "sgst_amount": (
                    float(inv.sgst_amount) if inv.sgst_amount is not None else None
                ),
                "igst_amount": (
                    float(inv.igst_amount) if inv.igst_amount is not None else None
                ),
            }
        )

    return {
        "user_id": user_id,
        "period": period,
        "count": len(items),
        "invoices": items,
    }


@router.get("/debug/gstr3b/{user_id}/{year}/{month}")
async def debug_gstr3b(
    user_id: str, year: int, month: int, db: AsyncSession = Depends(get_db)
):
    repo = InvoiceRepository(db)
    from calendar import monthrange

    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    summary = await prepare_gstr3b(
        user_id=user_id, period_start=start, period_end=end, repo=repo
    )
    json_body = make_gstr3b_json(settings.GST_SANDBOX_GSTIN, start, summary)

    sandbox_resp = await submit_gstr3b_to_sandbox(
        gstin=settings.GST_SANDBOX_GSTIN,
        period=start,
        summary=summary,
    )

    return {
        "json": json_body,
        "sandbox_response": sandbox_resp,
    }
