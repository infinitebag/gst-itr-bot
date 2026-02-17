# app/api/v1/routes/analytics.py
"""
Analytics endpoints: tax summary, anomaly detection, deadlines, AI insights.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.infrastructure.db.models import Invoice, User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok
from app.api.v1.schemas.analytics import (
    AnomalySchema,
    DeadlineSchema,
    InsightsRequest,
    InsightsResponse,
    TaxSummarySchema,
)

logger = logging.getLogger("api.v1.analytics")

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_user_invoices(
    user: User,
    db: AsyncSession,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list:
    """Fetch user's invoices with optional date filters."""
    q = select(Invoice).where(Invoice.user_id == user.id)
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    q = q.order_by(Invoice.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tax Summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=dict)
async def tax_summary(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate tax summary for the authenticated user's invoices."""
    from app.domain.services.tax_analytics import aggregate_invoices

    invoices = await _fetch_user_invoices(user, db, date_from, date_to)
    summary = aggregate_invoices(invoices)

    resp = TaxSummarySchema(
        period_start=summary.period_start,
        period_end=summary.period_end,
        total_invoices=summary.total_invoices,
        total_taxable_value=summary.total_taxable_value,
        total_tax=summary.total_tax,
        total_cgst=summary.total_cgst,
        total_sgst=summary.total_sgst,
        total_igst=summary.total_igst,
        total_amount=summary.total_amount,
        b2b_count=summary.b2b_count,
        b2c_count=summary.b2c_count,
        unique_suppliers=summary.unique_suppliers,
        unique_receivers=summary.unique_receivers,
        avg_invoice_value=summary.avg_invoice_value,
        tax_rate_distribution=summary.tax_rate_distribution,
    )

    return ok(data=resp.model_dump())


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------

@router.get("/anomalies", response_model=dict)
async def anomalies(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detect invoice anomalies (duplicates, invalid GSTINs, outliers, etc.)."""
    from app.domain.services.tax_analytics import detect_anomalies_dynamic

    invoices = await _fetch_user_invoices(user, db, date_from, date_to)
    report = await detect_anomalies_dynamic(invoices)

    resp = AnomalySchema(
        duplicate_invoice_numbers=report.duplicate_invoice_numbers,
        invalid_gstins=report.invalid_gstins,
        high_value_invoices=report.high_value_invoices,
        missing_fields=report.missing_fields,
        tax_rate_outliers=report.tax_rate_outliers,
        total_anomalies=report.total_anomalies,
    )

    return ok(data=resp.model_dump())


# ---------------------------------------------------------------------------
# Filing Deadlines (public — no auth required)
# ---------------------------------------------------------------------------

@router.get("/deadlines", response_model=dict)
async def deadlines():
    """Return upcoming GST/ITR filing deadlines based on the Indian tax calendar."""
    from app.domain.services.tax_analytics import get_filing_deadlines

    items = get_filing_deadlines()
    resp = [
        DeadlineSchema(
            form_name=d.form_name,
            due_date=d.due_date,
            period=d.period,
            days_remaining=d.days_remaining,
            status=d.status,
            description=d.description,
        ).model_dump()
        for d in items
    ]

    return ok(data=resp)


# ---------------------------------------------------------------------------
# AI Insights (GPT-4o powered)
# ---------------------------------------------------------------------------

@router.post("/insights", response_model=dict)
async def insights(
    body: InsightsRequest = InsightsRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate AI-powered tax insights using GPT-4o.

    Analyses the user's invoice summary, anomalies, and upcoming deadlines
    to produce actionable recommendations.
    """
    from app.domain.services.tax_analytics import (
        aggregate_invoices,
        detect_anomalies_dynamic,
        get_filing_deadlines,
        generate_ai_insights,
    )

    invoices = await _fetch_user_invoices(user, db)
    summary = aggregate_invoices(invoices)
    anomaly_report = await detect_anomalies_dynamic(invoices)
    deadline_list = get_filing_deadlines()

    text = await generate_ai_insights(summary, anomaly_report, deadline_list, lang=body.lang)

    return ok(data=InsightsResponse(insights=text).model_dump())
