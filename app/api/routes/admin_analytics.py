# app/api/routes/admin_analytics.py
"""
Admin analytics endpoints: AI-powered tax insights, anomaly detection, deadlines.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import require_admin_token
from app.config.settings import settings
from app.core.db import AsyncSessionLocal as async_session
from app.infrastructure.db.repositories.invoice_repository import InvoiceRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.domain.services.tax_analytics import (
    aggregate_invoices,
    detect_anomalies_dynamic as detect_anomalies,
    get_filing_deadlines,
    generate_ai_insights,
)

logger = logging.getLogger("admin_analytics")

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])

templates = Jinja2Templates(directory="app/templates/admin")


# ---------------------------------------------------------------------------
# JSON API: Tax summary + insights for a user
# ---------------------------------------------------------------------------
@router.get("/insights/{whatsapp_number}", dependencies=[Depends(require_admin_token)])
async def get_insights(
    whatsapp_number: str,
    period_start: str | None = None,
    period_end: str | None = None,
    lang: str = "en",
):
    """
    Get AI-powered tax insights for a user.
    Query params: period_start (YYYY-MM-DD), period_end (YYYY-MM-DD), lang
    """
    async with async_session() as db:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_whatsapp(whatsapp_number)
        if not user:
            raise HTTPException(404, "User not found")

        inv_repo = InvoiceRepository(db)

        if period_start and period_end:
            start = date.fromisoformat(period_start)
            end = date.fromisoformat(period_end)
            invoices = await inv_repo.list_for_period(user.id, start, end)
        else:
            invoices = await inv_repo.get_recent(user.id, limit=100)

    if not invoices:
        return JSONResponse({
            "status": "no_data",
            "message": "No invoices found for this user/period",
        })

    summary = aggregate_invoices(invoices)
    anomalies = await detect_anomalies(invoices)
    deadlines = get_filing_deadlines()

    ai_insights = await generate_ai_insights(summary, anomalies, deadlines, lang)

    return JSONResponse({
        "status": "ok",
        "summary": {
            "period": f"{summary.period_start} to {summary.period_end}",
            "total_invoices": summary.total_invoices,
            "total_taxable_value": float(summary.total_taxable_value),
            "total_tax": float(summary.total_tax),
            "total_cgst": float(summary.total_cgst),
            "total_sgst": float(summary.total_sgst),
            "total_igst": float(summary.total_igst),
            "total_amount": float(summary.total_amount),
            "b2b_count": summary.b2b_count,
            "b2c_count": summary.b2c_count,
            "avg_invoice_value": float(summary.avg_invoice_value),
        },
        "anomalies": {
            "total": anomalies.total_anomalies,
            "duplicates": len(anomalies.duplicate_invoice_numbers),
            "invalid_gstins": len(anomalies.invalid_gstins),
            "high_value_outliers": len(anomalies.high_value_invoices),
            "missing_fields": len(anomalies.missing_fields),
            "unusual_tax_rates": len(anomalies.tax_rate_outliers),
            "details": {
                "duplicate_invoice_numbers": anomalies.duplicate_invoice_numbers,
                "invalid_gstins": anomalies.invalid_gstins,
                "high_value_invoices": anomalies.high_value_invoices,
                "tax_rate_outliers": anomalies.tax_rate_outliers,
            },
        },
        "deadlines": [
            {
                "form": d.form_name,
                "due_date": str(d.due_date),
                "period": d.period,
                "days_remaining": d.days_remaining,
                "status": d.status,
                "description": d.description,
            }
            for d in deadlines
        ],
        "ai_insights": ai_insights,
    })


# ---------------------------------------------------------------------------
# JSON API: Anomaly detection only
# ---------------------------------------------------------------------------
@router.get("/anomalies/{whatsapp_number}", dependencies=[Depends(require_admin_token)])
async def get_anomalies(
    whatsapp_number: str,
):
    """Get invoice anomaly report for a user."""
    async with async_session() as db:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_whatsapp(whatsapp_number)
        if not user:
            raise HTTPException(404, "User not found")

        inv_repo = InvoiceRepository(db)
        invoices = await inv_repo.get_recent(user.id, limit=200)

    if not invoices:
        return JSONResponse({"status": "no_data", "anomalies": {}})

    anomalies = await detect_anomalies(invoices)

    return JSONResponse({
        "status": "ok",
        "total_invoices_checked": len(invoices),
        "total_anomalies": anomalies.total_anomalies,
        "duplicate_invoice_numbers": anomalies.duplicate_invoice_numbers,
        "invalid_gstins": anomalies.invalid_gstins,
        "high_value_invoices": anomalies.high_value_invoices,
        "missing_fields": anomalies.missing_fields,
        "tax_rate_outliers": anomalies.tax_rate_outliers,
    })


# ---------------------------------------------------------------------------
# JSON API: Filing deadlines
# ---------------------------------------------------------------------------
@router.get("/deadlines", dependencies=[Depends(require_admin_token)])
async def get_deadlines():
    """Get upcoming GST/ITR filing deadlines."""
    deadlines = get_filing_deadlines()

    return JSONResponse({
        "status": "ok",
        "deadlines": [
            {
                "form": d.form_name,
                "due_date": str(d.due_date),
                "period": d.period,
                "days_remaining": d.days_remaining,
                "status": d.status,
                "description": d.description,
            }
            for d in deadlines
        ],
    })
