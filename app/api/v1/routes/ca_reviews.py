# app/api/v1/routes/ca_reviews.py
"""
REST API endpoints for CA ITR and GST review workflows.

ITR:  list, detail, approve, request-changes, edit (recompute)
GST:  list, detail, approve, request-changes, submit to MasterGST
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.domain.services.ca_auth import get_current_ca
from app.infrastructure.audit import log_ca_action

# ITR workflow
from app.domain.services.itr_workflow import (
    transition_itr_draft,
    InvalidTransitionError,
    VALID_TRANSITIONS as ITR_TRANSITIONS,
)
from app.domain.services.itr_service import (
    ITR1Input,
    ITR2Input,
    ITR4Input,
    compute_itr1_dynamic as compute_itr1,
    compute_itr2_dynamic as compute_itr2,
    compute_itr4_dynamic as compute_itr4,
)

# GST workflow
from app.domain.services.gst_workflow import (
    transition_gst_filing,
    InvalidGSTTransitionError,
    VALID_TRANSITIONS as GST_TRANSITIONS,
)

from app.infrastructure.db.models import CAUser, ITRDraft, FilingRecord, User
from app.infrastructure.db.repositories.itr_draft_repository import ITRDraftRepository
from app.infrastructure.db.repositories.filing_repository import FilingRepository

from app.api.v1.envelope import ok, paginated
from app.api.v1.schemas.ca import (
    ITRReviewOut,
    ITREditRequest,
    ReviewAction,
    GSTReviewOut,
)

logger = logging.getLogger("api.v1.ca_reviews")

router = APIRouter(prefix="/ca", tags=["CA Reviews"])


# ═══════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════

def _safe_json_load(raw: str | None) -> dict | list | None:
    """Safely parse a JSON string; return None on failure."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# ITR helpers
# ---------------------------------------------------------------------------

def _draft_to_out(draft: ITRDraft) -> dict[str, Any]:
    """Convert an ITRDraft ORM object to a dict matching ITRReviewOut."""
    result_data = _safe_json_load(draft.result_json)
    input_data = _safe_json_load(draft.input_json)
    merged_data = _safe_json_load(draft.merged_data_json)
    mismatch_data = _safe_json_load(draft.mismatch_json)
    checklist_data = _safe_json_load(draft.checklist_json)
    gst_ids = _safe_json_load(draft.linked_gst_filing_ids)

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
        "allowed_transitions": ITR_TRANSITIONS.get(draft.status, []),
    }


async def _get_draft_or_404(
    draft_id: UUID,
    ca: CAUser,
    db: AsyncSession,
) -> ITRDraft:
    """Fetch an ITR draft and verify it belongs to this CA."""
    repo = ITRDraftRepository(db)
    draft = await repo.get_by_id(draft_id)
    if draft is None or draft.ca_id != ca.id:
        raise HTTPException(status_code=404, detail="ITR draft not found")
    return draft


async def _get_notify_wa_id(user_id: Any, db: AsyncSession) -> str | None:
    """Look up WhatsApp number for a user (for notifications)."""
    if not user_id:
        return None
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    return user.whatsapp_number if user else None


# ---------------------------------------------------------------------------
# GST helpers
# ---------------------------------------------------------------------------

def _filing_to_out(filing: FilingRecord) -> dict[str, Any]:
    """Convert a FilingRecord ORM object to a dict matching GSTReviewOut."""
    payload = _safe_json_load(filing.payload_json)
    response_data = _safe_json_load(filing.response_json)

    invoice_count = 0
    total_taxable = 0.0
    total_tax = 0.0
    is_nil = False
    invoices: list[dict[str, Any]] = []

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
        "allowed_transitions": GST_TRANSITIONS.get(filing.status, []),
    }


async def _get_filing_or_404(
    filing_id: UUID,
    ca: CAUser,
    db: AsyncSession,
) -> FilingRecord:
    """Fetch a GST filing and verify it belongs to this CA."""
    repo = FilingRepository(db)
    filing = await repo.get_by_id(filing_id)
    if filing is None or filing.ca_id != ca.id:
        raise HTTPException(status_code=404, detail="GST filing not found")
    return filing


# ═══════════════════════════════════════════════════════════════════════════
# ITR Review Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/itr-reviews", response_model=dict)
async def list_itr_reviews(
    status_filter: str = Query("", alias="status", description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """List ITR drafts for this CA's clients (paginated, filterable)."""
    repo = ITRDraftRepository(db)

    # Get filtered list
    filter_status = status_filter.strip() if status_filter else None
    drafts = await repo.get_all_for_ca(ca.id, status=filter_status)

    total = len(drafts)
    page = drafts[offset: offset + limit]

    items = [_draft_to_out(d) for d in page]
    return paginated(items=items, total=total, limit=limit, offset=offset)


@router.get("/itr-reviews/{draft_id}", response_model=dict)
async def get_itr_review(
    draft_id: UUID,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Get full detail of an ITR draft (computation, mismatches, checklist)."""
    draft = await _get_draft_or_404(draft_id, ca, db)
    return ok(data=_draft_to_out(draft))


@router.post("/itr-reviews/{draft_id}/approve", response_model=dict)
async def approve_itr_draft(
    draft_id: UUID,
    body: ReviewAction | None = None,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Approve an ITR draft — sets status to ca_approved."""
    draft = await _get_draft_or_404(draft_id, ca, db)
    notify_wa_id = await _get_notify_wa_id(draft.user_id, db)

    ca_notes = body.ca_notes.strip() if body and body.ca_notes else None

    try:
        await transition_itr_draft(
            draft_id,
            "ca_approved",
            db,
            ca_notes=ca_notes,
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

    # Re-fetch updated draft
    updated = await _get_draft_or_404(draft_id, ca, db)
    return ok(data=_draft_to_out(updated), message="Draft approved")


@router.post("/itr-reviews/{draft_id}/request-changes", response_model=dict)
async def request_itr_changes(
    draft_id: UUID,
    body: ReviewAction,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Request changes on an ITR draft — notifies user with CA notes."""
    if not body.ca_notes or not body.ca_notes.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ca_notes is required when requesting changes",
        )

    draft = await _get_draft_or_404(draft_id, ca, db)
    notify_wa_id = await _get_notify_wa_id(draft.user_id, db)

    try:
        await transition_itr_draft(
            draft_id,
            "changes_requested",
            db,
            ca_notes=body.ca_notes.strip(),
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
                "ca_notes": body.ca_notes.strip()[:200],
            },
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    updated = await _get_draft_or_404(draft_id, ca, db)
    return ok(data=_draft_to_out(updated), message="Changes requested")


@router.put("/itr-reviews/{draft_id}", response_model=dict)
async def edit_itr_draft(
    draft_id: UUID,
    body: ITREditRequest,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """
    Edit input fields on an ITR draft and recompute the tax.

    Send ``input_overrides`` as key-value pairs; the endpoint merges them
    with existing input and re-runs the ITR computation engine.
    """
    draft = await _get_draft_or_404(draft_id, ca, db)
    repo = ITRDraftRepository(db)

    current_input = _safe_json_load(draft.input_json) or {}

    # Merge overrides
    for key, val in body.input_overrides.items():
        if val is not None:
            try:
                current_input[key] = float(val)
            except (ValueError, TypeError):
                current_input[key] = str(val).strip()

    # Recompute
    try:
        if draft.form_type == "ITR-1":
            inp = ITR1Input(**{
                k: current_input.get(k, 0)
                for k in ITR1Input.__dataclass_fields__
            })
            result = await compute_itr1(inp)
        elif draft.form_type == "ITR-2":
            inp = ITR2Input(**{
                k: current_input.get(k, 0)
                for k in ITR2Input.__dataclass_fields__
            })
            result = await compute_itr2(inp)
        elif draft.form_type == "ITR-4":
            inp = ITR4Input(**{
                k: current_input.get(k, 0)
                for k in ITR4Input.__dataclass_fields__
            })
            result = await compute_itr4(inp)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown form type: {draft.form_type}",
            )

        result_dict = {
            "recommended_regime": result.recommended_regime,
            "savings": float(result.savings),
            "old_regime": asdict(result.old_regime),
            "new_regime": asdict(result.new_regime),
        }

        update_kwargs: dict[str, str] = {
            "input_json": json.dumps(current_input, default=str),
            "result_json": json.dumps(result_dict, default=str),
        }
        await repo.update_fields(draft_id, **update_kwargs)

        # Optionally update CA notes
        if body.ca_notes:
            await repo.update_status(
                draft_id,
                draft.status,  # keep same status
                ca_notes=body.ca_notes.strip(),
            )

        await db.commit()

        log_ca_action(
            "edit_itr_draft",
            ca_id=ca.id,
            ca_email=ca.email,
            details={"draft_id": str(draft_id), "form_type": draft.form_type},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to recompute ITR draft %s", draft_id)
        raise HTTPException(
            status_code=400,
            detail=f"Recomputation failed: {e}",
        )

    updated = await _get_draft_or_404(draft_id, ca, db)
    return ok(data=_draft_to_out(updated), message="Draft updated and recomputed")


# ═══════════════════════════════════════════════════════════════════════════
# GST Review Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/gst-reviews", response_model=dict)
async def list_gst_reviews(
    status_filter: str = Query("", alias="status", description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """List GST filings for this CA's clients (paginated, filterable)."""
    repo = FilingRepository(db)

    filter_status = status_filter.strip() if status_filter else None
    filings = await repo.get_for_ca(ca.id, filing_type="GST", status=filter_status)

    total = len(filings)
    page = filings[offset: offset + limit]

    items = [_filing_to_out(f) for f in page]
    return paginated(items=items, total=total, limit=limit, offset=offset)


@router.get("/gst-reviews/{filing_id}", response_model=dict)
async def get_gst_review(
    filing_id: UUID,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Get full detail of a GST filing (invoices, summary, payload)."""
    filing = await _get_filing_or_404(filing_id, ca, db)
    return ok(data=_filing_to_out(filing))


@router.post("/gst-reviews/{filing_id}/approve", response_model=dict)
async def approve_gst_filing(
    filing_id: UUID,
    body: ReviewAction | None = None,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Approve a GST filing — sets status to ca_approved."""
    filing = await _get_filing_or_404(filing_id, ca, db)
    notify_wa_id = await _get_notify_wa_id(filing.user_id, db)

    ca_notes = body.ca_notes.strip() if body and body.ca_notes else None

    try:
        await transition_gst_filing(
            filing_id,
            "ca_approved",
            db,
            ca_notes=ca_notes,
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

    updated = await _get_filing_or_404(filing_id, ca, db)
    return ok(data=_filing_to_out(updated), message="Filing approved")


@router.post("/gst-reviews/{filing_id}/request-changes", response_model=dict)
async def request_gst_changes(
    filing_id: UUID,
    body: ReviewAction,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Request changes on a GST filing — notifies user with CA notes."""
    if not body.ca_notes or not body.ca_notes.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ca_notes is required when requesting changes",
        )

    filing = await _get_filing_or_404(filing_id, ca, db)
    notify_wa_id = await _get_notify_wa_id(filing.user_id, db)

    try:
        await transition_gst_filing(
            filing_id,
            "changes_requested",
            db,
            ca_notes=body.ca_notes.strip(),
            notify_wa_id=notify_wa_id,
        )
        log_ca_action(
            "request_changes_gst_filing",
            ca_id=ca.id,
            ca_email=ca.email,
            details={
                "filing_id": str(filing_id),
                "form_type": filing.form_type,
                "ca_notes": body.ca_notes.strip()[:200],
            },
        )
    except InvalidGSTTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    updated = await _get_filing_or_404(filing_id, ca, db)
    return ok(data=_filing_to_out(updated), message="Changes requested")


@router.post("/gst-reviews/{filing_id}/submit", response_model=dict)
async def submit_gst_filing(
    filing_id: UUID,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit an approved GST filing to MasterGST.

    The filing must be in ``ca_approved`` status. On success, transitions
    to ``submitted``; on failure, transitions to ``error``.
    """
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
    notify_wa_id = await _get_notify_wa_id(filing.user_id, db)

    try:
        is_nil = payload.get("is_nil", False)
        response_data: dict[str, Any] = {}
        ref_number = None

        if is_nil:
            from app.domain.services.gst_service import file_nil_return_mastergst
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
        # Transition to error state
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
        raise HTTPException(
            status_code=500,
            detail=f"Submission failed: {e}",
        )

    updated = await _get_filing_or_404(filing_id, ca, db)
    return ok(data=_filing_to_out(updated), message="Filing submitted to MasterGST")
