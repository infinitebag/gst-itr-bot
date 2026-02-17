# app/api/routes/ca_gst_review.py
"""
CA GST Review Panel — view, approve, submit, reject GST filing drafts.
All routes require JWT authentication via ``get_current_ca``.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.domain.services.ca_auth import get_current_ca
from app.infrastructure.audit import log_ca_action
from app.domain.services.gst_workflow import (
    transition_gst_filing,
    InvalidGSTTransitionError,
    VALID_TRANSITIONS,
)
from app.infrastructure.db.models import CAUser, FilingRecord, User, BusinessClient
from app.infrastructure.db.repositories.filing_repository import FilingRepository

logger = logging.getLogger("ca_gst_review")

router = APIRouter(prefix="/ca", tags=["ca-gst-review"])
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json_load(raw: str | None) -> dict | list | None:
    """Safely parse a JSON string; return None on failure."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _filing_to_display(filing: FilingRecord) -> dict[str, Any]:
    """Convert a FilingRecord ORM object to a template-friendly dict."""
    payload = _safe_json_load(filing.payload_json)
    response_data = _safe_json_load(filing.response_json)

    # Extract invoice summary from payload
    invoice_count = 0
    total_taxable = 0.0
    total_tax = 0.0
    is_nil = False
    invoices = []

    if payload:
        is_nil = payload.get("is_nil", False)
        invoices = payload.get("invoices", [])
        invoice_count = len(invoices)
        for inv in invoices:
            total_taxable += float(inv.get("taxable_value", 0) or 0)
            total_tax += float(inv.get("tax_amount", 0) or 0)

    return {
        "id": str(filing.id),
        "filing_type": filing.filing_type,
        "form_type": filing.form_type,
        "gstin": filing.gstin,
        "period": filing.period,
        "status": filing.status,
        "ca_notes": filing.ca_notes,
        "ca_reviewed_at": filing.ca_reviewed_at,
        "created_at": filing.created_at,
        "updated_at": getattr(filing, "updated_at", filing.created_at),
        "reference_number": filing.reference_number,
        "payload": payload,
        "response_data": response_data,
        "is_nil": is_nil,
        "invoice_count": invoice_count,
        "total_taxable": total_taxable,
        "total_tax": total_tax,
        "invoices": invoices,
        "allowed_transitions": VALID_TRANSITIONS.get(filing.status, []),
    }


async def _get_filing_or_404(
    filing_id: UUID,
    ca: CAUser,
    db: AsyncSession,
) -> FilingRecord:
    """Fetch a GST filing and verify it belongs to this CA's clients."""
    repo = FilingRepository(db)
    filing = await repo.get_by_id(filing_id)
    if filing is None or filing.ca_id != ca.id:
        raise HTTPException(status_code=404, detail="GST filing not found")
    return filing


# ---------------------------------------------------------------------------
# GST Review List
# ---------------------------------------------------------------------------

@router.get("/gst-reviews", response_class=HTMLResponse)
async def gst_review_list(
    request: Request,
    status: str = Query("", description="Filter by status"),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """List GST filings for this CA's clients."""
    repo = FilingRepository(db)

    if status and status.strip():
        filings = await repo.get_for_ca(ca.id, filing_type="GST", status=status.strip())
    else:
        filings = await repo.get_for_ca(ca.id, filing_type="GST")

    # Enrich with user info
    rows: list[dict[str, Any]] = []
    for filing in filings:
        user_name = "Unknown"
        if filing.user_id:
            stmt = select(User).where(User.id == filing.user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                user_name = user.name or user.whatsapp_number or "Unknown"

        display = _filing_to_display(filing)
        display["user_name"] = user_name
        rows.append(display)

    pending_count = sum(1 for r in rows if r["status"] == "pending_ca_review")

    return templates.TemplateResponse(
        "ca/gst_review_list.html",
        {
            "request": request,
            "title": "GST Reviews",
            "ca": ca,
            "filings": rows,
            "pending_count": pending_count,
            "filter_status": status,
        },
    )


# ---------------------------------------------------------------------------
# GST Review Detail
# ---------------------------------------------------------------------------

@router.get("/gst-reviews/{filing_id}", response_class=HTMLResponse)
async def gst_review_detail(
    request: Request,
    filing_id: UUID,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Detailed view of a GST filing — invoices, summary, status."""
    filing = await _get_filing_or_404(filing_id, ca, db)
    display = _filing_to_display(filing)

    # Get user info
    user_name = "Unknown"
    user_wa = ""
    if filing.user_id:
        stmt = select(User).where(User.id == filing.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            user_name = user.name or user.whatsapp_number or "Unknown"
            user_wa = user.whatsapp_number or ""

    display["user_name"] = user_name
    display["user_wa"] = user_wa

    return templates.TemplateResponse(
        "ca/gst_review_detail.html",
        {
            "request": request,
            "title": f"GST Review: {display['form_type']} - {display['period']}",
            "ca": ca,
            "filing": display,
        },
    )


# ---------------------------------------------------------------------------
# Approve Filing
# ---------------------------------------------------------------------------

@router.post("/gst-reviews/{filing_id}/approve")
async def approve_filing(
    request: Request,
    filing_id: UUID,
    ca_notes: str = Form(""),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Approve a GST filing — sets status to ca_approved."""
    filing = await _get_filing_or_404(filing_id, ca, db)

    # Get user WhatsApp for notification
    notify_wa_id = None
    if filing.user_id:
        stmt = select(User).where(User.id == filing.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            notify_wa_id = user.whatsapp_number

    try:
        await transition_gst_filing(
            filing_id,
            "ca_approved",
            db,
            ca_notes=ca_notes.strip() or None,
            notify_wa_id=notify_wa_id,
        )
        log_ca_action(
            "approve_gst_filing",
            ca_id=ca.id,
            ca_email=ca.email,
            details={
                "filing_id": str(filing_id),
                "form_type": filing.form_type,
                "period": filing.period,
            },
        )
    except InvalidGSTTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(url=f"/ca/gst-reviews/{filing_id}", status_code=303)


# ---------------------------------------------------------------------------
# Submit to MasterGST (CA submits on behalf of user)
# ---------------------------------------------------------------------------

@router.post("/gst-reviews/{filing_id}/submit")
async def submit_filing(
    request: Request,
    filing_id: UUID,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """CA submits an approved GST filing to MasterGST."""
    filing = await _get_filing_or_404(filing_id, ca, db)

    if filing.status != "ca_approved":
        raise HTTPException(
            status_code=400,
            detail="Filing must be approved before submission",
        )

    payload = _safe_json_load(filing.payload_json)
    if not payload:
        raise HTTPException(status_code=400, detail="No filing payload found")

    gstin = filing.gstin or ""
    period = filing.period or ""
    form_type = filing.form_type

    # Get user WhatsApp for notification
    notify_wa_id = None
    if filing.user_id:
        stmt = select(User).where(User.id == filing.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            notify_wa_id = user.whatsapp_number

    try:
        is_nil = payload.get("is_nil", False)
        response_data: dict[str, Any] = {}
        ref_number = None

        if is_nil:
            from app.domain.services.gst_service import (
                file_nil_return_mastergst,
            )
            result_msg = await file_nil_return_mastergst(gstin, period, form_type)
            response_data = {"message": result_msg}
        else:
            invoices = payload.get("invoices", [])
            if "GSTR-1" in form_type:
                from app.domain.services.gst_service import file_gstr1_from_session
                result = await file_gstr1_from_session(gstin, period, invoices)
            else:
                from app.domain.services.gst_service import file_gstr3b_from_session
                result = await file_gstr3b_from_session(gstin, period, invoices)

            if hasattr(result, "reference_number"):
                ref_number = result.reference_number
            if hasattr(result, "status"):
                response_data["status"] = result.status
            if hasattr(result, "message"):
                response_data["message"] = result.message

        # Transition to submitted
        await transition_gst_filing(
            filing_id,
            "submitted",
            db,
            reference_number=ref_number,
            response_json=response_data,
            notify_wa_id=notify_wa_id,
        )

        log_ca_action(
            "submit_gst_filing",
            ca_id=ca.id,
            ca_email=ca.email,
            details={
                "filing_id": str(filing_id),
                "form_type": form_type,
                "period": period,
                "gstin": gstin,
            },
        )
    except InvalidGSTTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("MasterGST submission failed for filing %s", filing_id)
        # Transition to error
        try:
            await transition_gst_filing(
                filing_id,
                "error",
                db,
                ca_notes=f"Submission failed: {str(e)[:200]}",
                notify_wa_id=notify_wa_id,
            )
        except Exception:
            logger.exception("Failed to transition to error state")
        raise HTTPException(status_code=500, detail=f"Submission failed: {e}")

    return RedirectResponse(url=f"/ca/gst-reviews/{filing_id}", status_code=303)


# ---------------------------------------------------------------------------
# Request Changes
# ---------------------------------------------------------------------------

@router.post("/gst-reviews/{filing_id}/request-changes")
async def request_changes(
    request: Request,
    filing_id: UUID,
    ca_notes: str = Form(...),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Request changes on a GST filing — notifies user with CA notes."""
    filing = await _get_filing_or_404(filing_id, ca, db)

    # Get user WhatsApp for notification
    notify_wa_id = None
    if filing.user_id:
        stmt = select(User).where(User.id == filing.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            notify_wa_id = user.whatsapp_number

    try:
        await transition_gst_filing(
            filing_id,
            "changes_requested",
            db,
            ca_notes=ca_notes.strip(),
            notify_wa_id=notify_wa_id,
        )
        log_ca_action(
            "request_changes_gst_filing",
            ca_id=ca.id,
            ca_email=ca.email,
            details={
                "filing_id": str(filing_id),
                "form_type": filing.form_type,
                "ca_notes": ca_notes.strip()[:200],
            },
        )
    except InvalidGSTTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(url=f"/ca/gst-reviews/{filing_id}", status_code=303)
