# app/api/v1/routes/gst.py
"""
GST-related endpoints: GSTR-3B preparation, NIL filing, current period.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.infrastructure.db.models import Invoice, User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok
from app.api.v1.schemas.gst import (
    CurrentPeriodResponse,
    Gstr3bRequest,
    Gstr3bResponse,
    NilFilingRequest,
    NilFilingResponse,
)

logger = logging.getLogger("api.v1.gst")

router = APIRouter(prefix="/gst", tags=["GST"])


@router.post("/gstr3b", response_model=dict)
async def prepare_gstr3b(
    body: Gstr3bRequest = Gstr3bRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Prepare a GSTR-3B summary from the authenticated user's invoices.

    If ``demo=true``, returns sample data without querying the database.
    """
    from app.domain.services.gst_service import prepare_gstr3b, get_current_gst_period

    if body.demo:
        summary = prepare_gstr3b(demo=True)
    else:
        # Fetch user's invoices, optionally filtered by period
        q = select(Invoice).where(Invoice.user_id == user.id)
        if body.period:
            # Filter invoices whose date falls in the requested period (YYYY-MM)
            year, month = body.period.split("-")
            from datetime import date

            start = date(int(year), int(month), 1)
            if int(month) == 12:
                end = date(int(year) + 1, 1, 1)
            else:
                end = date(int(year), int(month) + 1, 1)
            q = q.where(Invoice.invoice_date >= start, Invoice.invoice_date < end)

        result = await db.execute(q)
        invoices = result.scalars().all()

        # Convert to dicts for the service
        inv_dicts = []
        for inv in invoices:
            inv_dicts.append({
                "taxable_value": float(inv.taxable_value),
                "tax_amount": float(inv.tax_amount),
                "cgst_amount": float(inv.cgst_amount) if inv.cgst_amount else 0,
                "sgst_amount": float(inv.sgst_amount) if inv.sgst_amount else 0,
                "igst_amount": float(inv.igst_amount) if inv.igst_amount else 0,
                "recipient_gstin": inv.recipient_gstin,
                "place_of_supply": inv.place_of_supply,
            })

        summary = prepare_gstr3b(inv_dicts)

    # Convert dataclass to response schema
    resp = Gstr3bResponse(
        outward_taxable_supplies={
            "taxable_value": summary.outward_taxable_supplies.taxable_value,
            "igst": summary.outward_taxable_supplies.igst,
            "cgst": summary.outward_taxable_supplies.cgst,
            "sgst": summary.outward_taxable_supplies.sgst,
            "cess": summary.outward_taxable_supplies.cess,
        },
        inward_reverse_charge={
            "taxable_value": summary.inward_reverse_charge.taxable_value,
            "igst": summary.inward_reverse_charge.igst,
            "cgst": summary.inward_reverse_charge.cgst,
            "sgst": summary.inward_reverse_charge.sgst,
            "cess": summary.inward_reverse_charge.cess,
        },
        itc_eligible={
            "igst": summary.itc_eligible.igst,
            "cgst": summary.itc_eligible.cgst,
            "sgst": summary.itc_eligible.sgst,
            "cess": summary.itc_eligible.cess,
        },
        outward_nil_exempt=summary.outward_nil_exempt,
        outward_non_gst=summary.outward_non_gst,
    )

    period = body.period or get_current_gst_period()
    return ok(data=resp.model_dump(), message=f"GSTR-3B summary for period {period}")


@router.post("/nil-filing", response_model=dict)
async def nil_filing(
    body: NilFilingRequest,
    user: User = Depends(get_current_user),
):
    """
    Prepare a NIL GSTR-3B or GSTR-1 return (all zeros / no outward supplies).
    """
    from app.domain.services.gst_service import prepare_nil_gstr3b, prepare_nil_gstr1

    if body.form_type.lower() == "gstr1":
        result = prepare_nil_gstr1(body.gstin, body.period)
    else:
        result = prepare_nil_gstr3b(body.gstin, body.period)

    resp = NilFilingResponse(
        form_type=result.form_type,
        gstin=result.gstin,
        period=result.period,
        status=result.status,
        reference_number=result.reference_number,
        message=result.message,
        filed_at=result.filed_at,
    )

    return ok(data=resp.model_dump())


@router.get("/current-period", response_model=dict)
async def current_period():
    """Return the current GST return period string (YYYY-MM)."""
    from app.domain.services.gst_service import get_current_gst_period

    period = get_current_gst_period()
    return ok(data=CurrentPeriodResponse(period=period).model_dump())
