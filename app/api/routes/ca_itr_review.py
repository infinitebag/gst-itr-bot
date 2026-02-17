# app/api/routes/ca_itr_review.py
"""
CA ITR Review Panel — view, approve, reject, edit ITR drafts for clients.
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
from app.domain.services.itr_workflow import (
    transition_itr_draft,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)
from app.domain.services.itr_service import (
    ITR1Input,
    ITR2Input,
    ITR4Input,
    compute_itr1_dynamic as compute_itr1,
    compute_itr2_dynamic as compute_itr2,
    compute_itr4_dynamic as compute_itr4,
)
from app.domain.services.itr_json import (
    generate_itr1_json,
    generate_itr4_json,
)
from app.infrastructure.db.models import CAUser, ITRDraft, User, BusinessClient
from app.infrastructure.db.repositories.itr_draft_repository import ITRDraftRepository

logger = logging.getLogger("ca_itr_review")

router = APIRouter(prefix="/ca", tags=["ca-itr-review"])
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


def _draft_to_display(draft: ITRDraft) -> dict[str, Any]:
    """Convert an ITRDraft ORM object to a template-friendly dict."""
    result_data = _safe_json_load(draft.result_json)
    input_data = _safe_json_load(draft.input_json)
    merged_data = _safe_json_load(draft.merged_data_json)
    mismatch_data = _safe_json_load(draft.mismatch_json)
    checklist_data = _safe_json_load(draft.checklist_json)
    gst_ids = _safe_json_load(draft.linked_gst_filing_ids)

    # Extract key figures from result
    recommended_regime = None
    tax_payable = None
    savings = None
    if result_data:
        recommended_regime = result_data.get("recommended_regime")
        savings = result_data.get("savings")
        regime_key = "old_regime" if recommended_regime == "old" else "new_regime"
        regime_data = result_data.get(regime_key, {})
        tax_payable = regime_data.get("tax_payable")

    return {
        "id": str(draft.id),
        "form_type": draft.form_type,
        "assessment_year": draft.assessment_year,
        "pan": draft.pan,
        "status": draft.status,
        "ca_notes": draft.ca_notes,
        "ca_reviewed_at": draft.ca_reviewed_at,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "input_data": input_data,
        "result_data": result_data,
        "merged_data": merged_data,
        "mismatch_data": mismatch_data,
        "checklist_data": checklist_data,
        "linked_gst_filing_ids": gst_ids or [],
        "recommended_regime": recommended_regime,
        "tax_payable": tax_payable,
        "savings": savings,
        "allowed_transitions": VALID_TRANSITIONS.get(draft.status, []),
    }


async def _get_draft_or_404(
    draft_id: UUID,
    ca: CAUser,
    db: AsyncSession,
) -> ITRDraft:
    """Fetch an ITR draft and verify it belongs to this CA's clients."""
    repo = ITRDraftRepository(db)
    draft = await repo.get_by_id(draft_id)
    if draft is None or draft.ca_id != ca.id:
        raise HTTPException(status_code=404, detail="ITR draft not found")
    return draft


# ---------------------------------------------------------------------------
# ITR Review List
# ---------------------------------------------------------------------------

@router.get("/itr-reviews", response_class=HTMLResponse)
async def itr_review_list(
    request: Request,
    status: str = Query("", description="Filter by status"),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """List ITR drafts for this CA's clients."""
    repo = ITRDraftRepository(db)

    if status and status.strip():
        drafts = await repo.get_all_for_ca(ca.id, status=status.strip())
    else:
        drafts = await repo.get_all_for_ca(ca.id)

    # Enrich with user info
    rows: list[dict[str, Any]] = []
    for draft in drafts:
        # Get user name
        user_name = "Unknown"
        if draft.user_id:
            stmt = select(User).where(User.id == draft.user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                user_name = user.name or user.whatsapp_number or "Unknown"

        display = _draft_to_display(draft)
        display["user_name"] = user_name
        rows.append(display)

    # Count pending reviews
    pending_count = sum(1 for r in rows if r["status"] == "pending_ca_review")

    return templates.TemplateResponse(
        "ca/itr_review_list.html",
        {
            "request": request,
            "title": "ITR Reviews",
            "ca": ca,
            "drafts": rows,
            "pending_count": pending_count,
            "filter_status": status,
        },
    )


# ---------------------------------------------------------------------------
# ITR Review Detail
# ---------------------------------------------------------------------------

@router.get("/itr-reviews/{draft_id}", response_class=HTMLResponse)
async def itr_review_detail(
    request: Request,
    draft_id: UUID,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Detailed view of an ITR draft — computation, mismatches, checklist."""
    draft = await _get_draft_or_404(draft_id, ca, db)
    display = _draft_to_display(draft)

    # Get user info
    user_name = "Unknown"
    user_wa = ""
    if draft.user_id:
        stmt = select(User).where(User.id == draft.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            user_name = user.name or user.whatsapp_number or "Unknown"
            user_wa = user.whatsapp_number or ""

    display["user_name"] = user_name
    display["user_wa"] = user_wa

    return templates.TemplateResponse(
        "ca/itr_review_detail.html",
        {
            "request": request,
            "title": f"ITR Review: {display['form_type']} - {display['assessment_year']}",
            "ca": ca,
            "draft": display,
        },
    )


# ---------------------------------------------------------------------------
# Approve Draft
# ---------------------------------------------------------------------------

@router.post("/itr-reviews/{draft_id}/approve")
async def approve_draft(
    request: Request,
    draft_id: UUID,
    ca_notes: str = Form(""),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Approve an ITR draft — sets status to ca_approved and notifies user."""
    draft = await _get_draft_or_404(draft_id, ca, db)

    # Get user WhatsApp for notification
    notify_wa_id = None
    if draft.user_id:
        stmt = select(User).where(User.id == draft.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            notify_wa_id = user.whatsapp_number

    try:
        await transition_itr_draft(
            draft_id,
            "ca_approved",
            db,
            ca_notes=ca_notes.strip() or None,
            notify_wa_id=notify_wa_id,
        )
        await db.commit()
        log_ca_action(
            "approve_itr_draft",
            ca_id=ca.id,
            ca_email=ca.email,
            details={"draft_id": str(draft_id), "form_type": draft.form_type},
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(url=f"/ca/itr-reviews/{draft_id}", status_code=303)


# ---------------------------------------------------------------------------
# Request Changes
# ---------------------------------------------------------------------------

@router.post("/itr-reviews/{draft_id}/request-changes")
async def request_changes(
    request: Request,
    draft_id: UUID,
    ca_notes: str = Form(...),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Request changes on an ITR draft — notifies user with CA notes."""
    draft = await _get_draft_or_404(draft_id, ca, db)

    # Get user WhatsApp for notification
    notify_wa_id = None
    if draft.user_id:
        stmt = select(User).where(User.id == draft.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            notify_wa_id = user.whatsapp_number

    try:
        await transition_itr_draft(
            draft_id,
            "changes_requested",
            db,
            ca_notes=ca_notes.strip(),
            notify_wa_id=notify_wa_id,
        )
        await db.commit()
        log_ca_action(
            "request_changes_itr_draft",
            ca_id=ca.id,
            ca_email=ca.email,
            details={
                "draft_id": str(draft_id),
                "form_type": draft.form_type,
                "ca_notes": ca_notes.strip()[:200],
            },
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(url=f"/ca/itr-reviews/{draft_id}", status_code=303)


# ---------------------------------------------------------------------------
# Edit Draft Fields (CA edits computation inputs)
# ---------------------------------------------------------------------------

@router.post("/itr-reviews/{draft_id}/edit")
async def edit_draft(
    request: Request,
    draft_id: UUID,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """
    CA edits input fields on a draft and recomputes.
    Expects form fields matching the ITR input structure.
    """
    draft = await _get_draft_or_404(draft_id, ca, db)
    form_data = await request.form()

    repo = ITRDraftRepository(db)

    # Parse updated input from form
    current_input = _safe_json_load(draft.input_json) or {}

    # Update fields from form (only update provided, non-empty fields)
    for key in form_data:
        val = form_data[key]
        if val and str(val).strip():
            try:
                current_input[key] = float(val)
            except (ValueError, TypeError):
                current_input[key] = str(val).strip()

    # Recompute based on form type
    try:
        if draft.form_type == "ITR-1":
            inp = ITR1Input(**{k: current_input.get(k, 0) for k in ITR1Input.__dataclass_fields__})
            result = await compute_itr1(inp)
        elif draft.form_type == "ITR-2":
            inp = ITR2Input(**{k: current_input.get(k, 0) for k in ITR2Input.__dataclass_fields__})
            result = await compute_itr2(inp)
        elif draft.form_type == "ITR-4":
            inp = ITR4Input(**{k: current_input.get(k, 0) for k in ITR4Input.__dataclass_fields__})
            result = await compute_itr4(inp)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown form type: {draft.form_type}")

        # Update draft with new computation
        from dataclasses import asdict
        result_dict = {
            "recommended_regime": result.recommended_regime,
            "savings": float(result.savings),
            "old_regime": asdict(result.old_regime),
            "new_regime": asdict(result.new_regime),
        }

        await repo.update_fields(
            draft_id,
            input_json=json.dumps(current_input, default=str),
            result_json=json.dumps(result_dict, default=str),
        )
        await db.commit()

        log_ca_action(
            "edit_itr_draft",
            ca_id=ca.id,
            ca_email=ca.email,
            details={"draft_id": str(draft_id), "form_type": draft.form_type},
        )
    except Exception as e:
        logger.exception("Failed to recompute ITR draft %s", draft_id)
        raise HTTPException(status_code=400, detail=f"Recomputation failed: {e}")

    return RedirectResponse(url=f"/ca/itr-reviews/{draft_id}", status_code=303)


# ---------------------------------------------------------------------------
# Client ITR Filings (history)
# ---------------------------------------------------------------------------

@router.get("/clients/{client_id}/itr-filings", response_class=HTMLResponse)
async def client_itr_filings(
    request: Request,
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """List all ITR filings for a specific client."""
    # Verify client belongs to this CA
    stmt = select(BusinessClient).where(
        BusinessClient.id == client_id,
        BusinessClient.ca_id == ca.id,
    )
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Find user by whatsapp_number
    user = None
    if client.whatsapp_number:
        user_stmt = select(User).where(User.whatsapp_number == client.whatsapp_number)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

    # Get ITR drafts for this user
    drafts: list[dict[str, Any]] = []
    if user:
        repo = ITRDraftRepository(db)
        user_drafts = await repo.get_for_client_user(user.id)
        for draft in user_drafts:
            display = _draft_to_display(draft)
            display["user_name"] = client.name
            drafts.append(display)

    return templates.TemplateResponse(
        "ca/client_itr_filings.html",
        {
            "request": request,
            "title": f"ITR Filings: {client.name}",
            "ca": ca,
            "client": client,
            "drafts": drafts,
        },
    )
