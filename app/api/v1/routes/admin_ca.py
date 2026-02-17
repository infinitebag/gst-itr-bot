# app/api/v1/routes/admin_ca.py
"""
Admin REST API endpoints for CA management.

All endpoints require the ``X-Admin-Token`` header (or ``admin_session`` cookie).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token
from app.core.db import get_db
from app.infrastructure.audit import log_admin_action
from app.infrastructure.db.models import BusinessClient, CAUser, FilingRecord, ITRDraft, User
from app.infrastructure.db.repositories.filing_repository import FilingRepository
from app.infrastructure.db.repositories.itr_draft_repository import ITRDraftRepository
from app.infrastructure.db.repositories.ca_repository import BusinessClientRepository

from app.api.v1.envelope import ok
from app.api.v1.schemas.ca import (
    AdminCAOut, ClientOut, TransferRequest,
    AssignCARequest, UnassignedGSTItem, UnassignedITRItem, UnassignedQueueOut,
)

logger = logging.getLogger("api.v1.admin_ca")

router = APIRouter(prefix="/admin/ca", tags=["Admin CA Management"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _pending_gst_count(db: AsyncSession, ca_id: int) -> int:
    stmt = select(func.count(FilingRecord.id)).where(
        FilingRecord.ca_id == ca_id,
        FilingRecord.filing_type == "GST",
        FilingRecord.status == "pending_ca_review",
    )
    return (await db.execute(stmt)).scalar_one() or 0


async def _pending_itr_count(db: AsyncSession, ca_id: int) -> int:
    stmt = select(func.count(ITRDraft.id)).where(
        ITRDraft.ca_id == ca_id,
        ITRDraft.status == "pending_ca_review",
    )
    return (await db.execute(stmt)).scalar_one() or 0


async def _client_count(db: AsyncSession, ca_id: int) -> int:
    stmt = select(func.count(BusinessClient.id)).where(
        BusinessClient.ca_id == ca_id,
    )
    return (await db.execute(stmt)).scalar_one() or 0


async def _ca_to_out(db: AsyncSession, ca: CAUser) -> dict[str, Any]:
    """Build an AdminCAOut-compatible dict with stats."""
    return AdminCAOut(
        id=ca.id,
        email=ca.email,
        name=ca.name,
        phone=ca.phone,
        membership_number=ca.membership_number,
        active=ca.active,
        approved=ca.approved,
        approved_at=ca.approved_at,
        created_at=ca.created_at,
        last_login=ca.last_login,
        client_count=await _client_count(db, ca.id),
        pending_gst_count=await _pending_gst_count(db, ca.id),
        pending_itr_count=await _pending_itr_count(db, ca.id),
    ).model_dump()


async def _get_ca_or_404(ca_id: int, db: AsyncSession) -> CAUser:
    stmt = select(CAUser).where(CAUser.id == ca_id)
    result = await db.execute(stmt)
    ca = result.scalar_one_or_none()
    if ca is None:
        raise HTTPException(status_code=404, detail="CA not found")
    return ca


# ---------------------------------------------------------------------------
# List all CAs
# ---------------------------------------------------------------------------

@router.get("/list", response_model=dict)
async def list_cas(
    status_filter: str = Query("", alias="status", description="Filter: approved, pending, inactive"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """List all CAs with client counts and pending review stats."""
    stmt = select(CAUser).order_by(CAUser.created_at.desc())

    if status_filter == "approved":
        stmt = stmt.where(CAUser.approved.is_(True), CAUser.active.is_(True))
    elif status_filter == "pending":
        stmt = stmt.where(CAUser.approved.is_(False), CAUser.active.is_(True))
    elif status_filter == "inactive":
        stmt = stmt.where(CAUser.active.is_(False))

    result = await db.execute(stmt)
    ca_rows = list(result.scalars().all())

    items = [await _ca_to_out(db, ca) for ca in ca_rows]
    return ok(data=items)


# ---------------------------------------------------------------------------
# List pending CAs
# ---------------------------------------------------------------------------

@router.get("/pending", response_model=dict)
async def list_pending_cas(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """List CAs awaiting admin approval."""
    stmt = (
        select(CAUser)
        .where(CAUser.approved.is_(False), CAUser.active.is_(True))
        .order_by(CAUser.created_at.desc())
    )
    result = await db.execute(stmt)
    ca_rows = list(result.scalars().all())

    items = [await _ca_to_out(db, ca) for ca in ca_rows]
    return ok(data=items)


# ---------------------------------------------------------------------------
# Helpers — user lookup
# ---------------------------------------------------------------------------

async def _get_user(db: AsyncSession, user_id) -> User | None:
    """Resolve User record for WhatsApp notification."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Unassigned Filing Queue
# ---------------------------------------------------------------------------

@router.get("/queue", response_model=dict)
async def get_unassigned_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """List all filings (GST + ITR) where ca_id IS NULL and status is pending_ca_review."""
    filing_repo = FilingRepository(db)
    itr_repo = ITRDraftRepository(db)

    gst_records, gst_total = await filing_repo.get_unassigned_filings(limit=limit, offset=offset)
    itr_drafts, itr_total = await itr_repo.get_unassigned_drafts(limit=limit, offset=offset)

    # Enrich with user info
    gst_items = []
    for r in gst_records:
        user = await _get_user(db, r.user_id)
        payload = json.loads(r.payload_json) if r.payload_json else {}
        gst_items.append(UnassignedGSTItem(
            id=str(r.id),
            form_type=r.form_type,
            gstin=r.gstin,
            period=r.period,
            status=r.status,
            user_id=str(r.user_id),
            user_whatsapp=user.whatsapp_number if user else None,
            user_name=user.name if user else None,
            created_at=r.created_at,
            is_nil=payload.get("is_nil", False),
        ).model_dump())

    itr_items = []
    for d in itr_drafts:
        user = await _get_user(db, d.user_id)
        itr_items.append(UnassignedITRItem(
            id=str(d.id),
            form_type=d.form_type,
            assessment_year=d.assessment_year,
            pan=d.pan,
            status=d.status,
            user_id=str(d.user_id),
            user_whatsapp=user.whatsapp_number if user else None,
            user_name=user.name if user else None,
            created_at=d.created_at,
        ).model_dump())

    queue = UnassignedQueueOut(
        gst_filings=gst_items,
        itr_drafts=itr_items,
        gst_total=gst_total,
        itr_total=itr_total,
    )
    return ok(data=queue.model_dump())


@router.post("/queue/gst/{filing_id}/assign", response_model=dict)
async def assign_ca_to_gst_filing(
    filing_id: UUID,
    body: AssignCARequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Assign a CA to an unassigned GST filing. Optionally create a BusinessClient."""
    # Validate CA exists and is active + approved
    target_ca = await _get_ca_or_404(body.ca_id, db)
    if not target_ca.active or not target_ca.approved:
        raise HTTPException(status_code=400, detail="Target CA is not active or not approved")

    filing_repo = FilingRepository(db)
    filing = await filing_repo.get_by_id(filing_id)
    if not filing:
        raise HTTPException(status_code=404, detail="GST filing not found")
    if filing.ca_id is not None:
        raise HTTPException(status_code=400, detail="Filing already has a CA assigned")

    # Assign CA
    await filing_repo.assign_ca(filing_id, body.ca_id)

    # Optionally create BusinessClient for future auto-routing
    if body.create_business_client:
        user = await _get_user(db, filing.user_id)
        if user:
            client_repo = BusinessClientRepository(db)
            existing = await client_repo.get_by_whatsapp(user.whatsapp_number)
            if not existing:
                await client_repo.create(
                    ca_id=body.ca_id,
                    name=user.name or user.whatsapp_number,
                    whatsapp_number=user.whatsapp_number,
                    gstin=filing.gstin,
                )
                await db.commit()

    # Notify user via WhatsApp
    try:
        user = await _get_user(db, filing.user_id)
        if user:
            from app.infrastructure.external.whatsapp_client import send_whatsapp_text
            period = filing.period or ""
            msg = (
                f"Great news! A CA has been assigned to review your {filing.form_type}"
                f" for period {period}. You will be notified when they respond."
            )
            await send_whatsapp_text(user.whatsapp_number, msg)
    except Exception:
        logger.exception("Failed to notify user about CA assignment for filing %s", filing_id)

    log_admin_action(
        "assign_ca_to_gst_filing",
        admin_ip="api",
        details={
            "filing_id": str(filing_id),
            "ca_id": body.ca_id,
            "create_client": body.create_business_client,
        },
    )

    return ok(message=f"CA #{body.ca_id} assigned to GST filing {filing_id}")


@router.post("/queue/itr/{draft_id}/assign", response_model=dict)
async def assign_ca_to_itr_draft(
    draft_id: UUID,
    body: AssignCARequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Assign a CA to an unassigned ITR draft. Optionally create a BusinessClient."""
    target_ca = await _get_ca_or_404(body.ca_id, db)
    if not target_ca.active or not target_ca.approved:
        raise HTTPException(status_code=400, detail="Target CA is not active or not approved")

    itr_repo = ITRDraftRepository(db)
    draft = await itr_repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="ITR draft not found")
    if draft.ca_id is not None:
        raise HTTPException(status_code=400, detail="Draft already has a CA assigned")

    # Assign CA
    draft.ca_id = body.ca_id
    await db.commit()

    # Optionally create BusinessClient
    if body.create_business_client:
        user = await _get_user(db, draft.user_id)
        if user:
            client_repo = BusinessClientRepository(db)
            existing = await client_repo.get_by_whatsapp(user.whatsapp_number)
            if not existing:
                await client_repo.create(
                    ca_id=body.ca_id,
                    name=user.name or user.whatsapp_number,
                    whatsapp_number=user.whatsapp_number,
                    pan=draft.pan,
                )
                await db.commit()

    # Notify user
    try:
        user = await _get_user(db, draft.user_id)
        if user:
            from app.infrastructure.external.whatsapp_client import send_whatsapp_text
            msg = (
                f"Great news! A CA has been assigned to review your {draft.form_type}. "
                "You will be notified when they respond."
            )
            await send_whatsapp_text(user.whatsapp_number, msg)
    except Exception:
        logger.exception("Failed to notify user about CA assignment for draft %s", draft_id)

    log_admin_action(
        "assign_ca_to_itr_draft",
        admin_ip="api",
        details={
            "draft_id": str(draft_id),
            "ca_id": body.ca_id,
            "create_client": body.create_business_client,
        },
    )

    return ok(message=f"CA #{body.ca_id} assigned to ITR draft {draft_id}")


# ---------------------------------------------------------------------------
# CA detail
# ---------------------------------------------------------------------------

@router.get("/{ca_id}", response_model=dict)
async def get_ca_detail(
    ca_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Get full CA detail with stats."""
    ca = await _get_ca_or_404(ca_id, db)
    return ok(data=await _ca_to_out(db, ca))


# ---------------------------------------------------------------------------
# Approve CA
# ---------------------------------------------------------------------------

@router.post("/{ca_id}/approve", response_model=dict)
async def approve_ca(
    ca_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Approve a pending CA registration."""
    ca = await _get_ca_or_404(ca_id, db)

    if ca.approved:
        raise HTTPException(status_code=400, detail="CA is already approved")

    ca.approved = True
    ca.approved_at = datetime.now(timezone.utc)
    await db.commit()

    log_admin_action(
        "approve_ca",
        admin_ip="api",
        details={"ca_id": ca_id, "ca_email": ca.email},
    )

    return ok(data=await _ca_to_out(db, ca), message="CA approved")


# ---------------------------------------------------------------------------
# Reject CA
# ---------------------------------------------------------------------------

@router.post("/{ca_id}/reject", response_model=dict)
async def reject_ca(
    ca_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Reject a pending CA — deactivates the account."""
    ca = await _get_ca_or_404(ca_id, db)

    if not ca.active:
        raise HTTPException(status_code=400, detail="CA is already deactivated")

    ca.active = False
    await db.commit()

    log_admin_action(
        "reject_ca",
        admin_ip="api",
        details={"ca_id": ca_id, "ca_email": ca.email},
    )

    return ok(data=await _ca_to_out(db, ca), message="CA rejected")


# ---------------------------------------------------------------------------
# Toggle active status
# ---------------------------------------------------------------------------

@router.post("/{ca_id}/toggle-active", response_model=dict)
async def toggle_ca_active(
    ca_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Toggle a CA's active status (enable / disable)."""
    ca = await _get_ca_or_404(ca_id, db)

    ca.active = not ca.active
    await db.commit()

    log_admin_action(
        "toggle_ca_active",
        admin_ip="api",
        details={"ca_id": ca_id, "ca_email": ca.email, "new_active": ca.active},
    )

    return ok(
        data=await _ca_to_out(db, ca),
        message=f"CA {'activated' if ca.active else 'deactivated'}",
    )


# ---------------------------------------------------------------------------
# Transfer client between CAs
# ---------------------------------------------------------------------------

@router.post("/clients/{client_id}/transfer", response_model=dict)
async def transfer_client(
    client_id: int,
    body: TransferRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Transfer a business client from one CA to another."""
    # Fetch client
    client_stmt = select(BusinessClient).where(BusinessClient.id == client_id)
    client_result = await db.execute(client_stmt)
    client = client_result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # Fetch target CA and verify it is active + approved
    target_ca = await _get_ca_or_404(body.new_ca_id, db)
    if not target_ca.active or not target_ca.approved:
        raise HTTPException(
            status_code=400,
            detail="Target CA is not active or not approved",
        )

    old_ca_id = client.ca_id
    client.ca_id = body.new_ca_id
    await db.commit()

    log_admin_action(
        "transfer_client",
        admin_ip="api",
        details={
            "client_id": client_id,
            "from_ca_id": old_ca_id,
            "to_ca_id": body.new_ca_id,
        },
    )

    # Return the updated client
    out = ClientOut(
        id=client.id,
        name=client.name,
        gstin=client.gstin,
        pan=client.pan,
        whatsapp_number=client.whatsapp_number,
        email=client.email,
        business_type=client.business_type,
        address=client.address,
        state_code=client.state_code,
        notes=client.notes,
        status=client.status,
        ca_id=client.ca_id,
        created_at=client.created_at,
        updated_at=getattr(client, "updated_at", None),
    ).model_dump()

    return ok(data=out, message=f"Client transferred from CA #{old_ca_id} to CA #{body.new_ca_id}")
