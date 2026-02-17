# app/api/v1/routes/ca_deadlines.py
"""REST API endpoint for upcoming GST/ITR filing deadlines."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.domain.services.ca_auth import get_current_ca
from app.domain.services.tax_analytics import get_filing_deadlines
from app.infrastructure.db.models import CAUser

from app.api.v1.envelope import ok

router = APIRouter(prefix="/ca", tags=["CA Deadlines"])


@router.get("/deadlines", response_model=dict)
async def list_deadlines(
    ca: CAUser = Depends(get_current_ca),
):
    """
    Return upcoming GST and ITR filing deadlines.

    Deadlines are computed from the Indian tax calendar relative to today.
    Each deadline includes form name, due date, period, days remaining,
    urgency status (upcoming / due_soon / overdue), and a description.
    """
    deadlines = get_filing_deadlines()

    items = [
        {
            "form_name": d.form_name,
            "due_date": d.due_date.isoformat(),
            "period": d.period,
            "days_remaining": d.days_remaining,
            "status": d.status,
            "description": d.description,
        }
        for d in deadlines
    ]

    return ok(data=items)
