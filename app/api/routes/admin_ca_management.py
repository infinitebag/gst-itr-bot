# app/api/routes/admin_ca_management.py

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token, verify_admin_form_token
from app.core.db import get_db
from app.infrastructure.audit import log_admin_action
from app.infrastructure.db.models import BusinessClient, CAUser, FilingRecord, ITRDraft, User

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin/ca", tags=["admin-ca-management"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _pending_gst_count(db: AsyncSession, ca_id: int) -> int:
    """Count FilingRecords pending CA review for a given CA."""
    stmt = select(func.count(FilingRecord.id)).where(
        FilingRecord.ca_id == ca_id,
        FilingRecord.filing_type == "GST",
        FilingRecord.status == "pending_ca_review",
    )
    return (await db.execute(stmt)).scalar_one() or 0


async def _pending_itr_count(db: AsyncSession, ca_id: int) -> int:
    """Count ITRDrafts pending CA review for a given CA."""
    stmt = select(func.count(ITRDraft.id)).where(
        ITRDraft.ca_id == ca_id,
        ITRDraft.status == "pending_ca_review",
    )
    return (await db.execute(stmt)).scalar_one() or 0


async def _client_count(db: AsyncSession, ca_id: int) -> int:
    """Count BusinessClients belonging to a given CA."""
    stmt = select(func.count(BusinessClient.id)).where(
        BusinessClient.ca_id == ca_id,
    )
    return (await db.execute(stmt)).scalar_one() or 0


# ---------------------------------------------------------------------------
# GET  /admin/ca/list — List all CAs with stats
# ---------------------------------------------------------------------------


@router.get("/list")
async def ca_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
    status: str = Query("", alias="status"),
):
    stmt = select(CAUser).order_by(CAUser.created_at.desc())

    # Apply optional status filter
    if status == "approved":
        stmt = stmt.where(CAUser.approved.is_(True), CAUser.active.is_(True))
    elif status == "pending":
        stmt = stmt.where(CAUser.approved.is_(False), CAUser.active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(CAUser.active.is_(False))

    result = await db.execute(stmt)
    ca_rows: list[CAUser] = list(result.scalars().all())

    cas: list[dict[str, Any]] = []
    for ca in ca_rows:
        cas.append(
            {
                "id": ca.id,
                "email": ca.email,
                "name": ca.name,
                "phone": ca.phone,
                "membership_number": ca.membership_number,
                "active": ca.active,
                "approved": ca.approved,
                "approved_at": ca.approved_at.isoformat() if ca.approved_at else None,
                "created_at": ca.created_at.isoformat() if ca.created_at else None,
                "last_login": ca.last_login.isoformat() if ca.last_login else None,
                "client_count": await _client_count(db, ca.id),
                "pending_gst": await _pending_gst_count(db, ca.id),
                "pending_itr": await _pending_itr_count(db, ca.id),
            }
        )

    # Count CAs awaiting approval (for badge / header)
    pending_stmt = select(func.count(CAUser.id)).where(
        CAUser.approved.is_(False), CAUser.active.is_(True)
    )
    pending_count = (await db.execute(pending_stmt)).scalar_one() or 0

    return templates.TemplateResponse(
        "admin/ca_list.html",
        {
            "request": request,
            "title": "CA Management",
            "cas": cas,
            "filter_status": status,
            "pending_count": pending_count,
            "admin_token": "",  # SECURITY: Never expose ADMIN_API_KEY in HTML
        },
    )


# ---------------------------------------------------------------------------
# GET  /admin/ca/pending — List CAs awaiting approval
# ---------------------------------------------------------------------------


@router.get("/pending")
async def ca_pending(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    stmt = (
        select(CAUser)
        .where(CAUser.approved.is_(False), CAUser.active.is_(True))
        .order_by(CAUser.created_at.desc())
    )
    result = await db.execute(stmt)
    rows: list[CAUser] = list(result.scalars().all())

    pending_cas: list[dict[str, Any]] = []
    for ca in rows:
        pending_cas.append(
            {
                "id": ca.id,
                "email": ca.email,
                "name": ca.name,
                "phone": ca.phone,
                "membership_number": ca.membership_number,
                "created_at": ca.created_at.isoformat() if ca.created_at else None,
            }
        )

    return templates.TemplateResponse(
        "admin/ca_pending.html",
        {
            "request": request,
            "title": "Pending CA Approvals",
            "pending_cas": pending_cas,
            "admin_token": "",  # SECURITY: Never expose ADMIN_API_KEY in HTML
        },
    )


# ---------------------------------------------------------------------------
# GET  /admin/ca/queue — Unassigned filing queue
# ---------------------------------------------------------------------------


@router.get("/queue")
async def ca_unassigned_queue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """Admin HTML page showing filings not yet assigned to any CA."""

    # Unassigned GST filings
    gst_stmt = (
        select(FilingRecord)
        .where(FilingRecord.ca_id.is_(None), FilingRecord.status == "pending_ca_review")
        .order_by(FilingRecord.created_at.asc())
        .limit(100)
    )
    gst_result = await db.execute(gst_stmt)
    gst_records = list(gst_result.scalars().all())

    # Enrich GST with user info
    gst_filings = []
    for r in gst_records:
        user_stmt = select(User).where(User.id == r.user_id)
        user = (await db.execute(user_stmt)).scalar_one_or_none()
        import json as _json
        payload = _json.loads(r.payload_json) if r.payload_json else {}
        gst_filings.append({
            "id": str(r.id),
            "form_type": r.form_type,
            "gstin": r.gstin,
            "period": r.period,
            "user_whatsapp": user.whatsapp_number if user else None,
            "user_name": user.name if user else None,
            "is_nil": payload.get("is_nil", False),
            "created_at": r.created_at,
        })

    # Unassigned ITR drafts
    itr_stmt = (
        select(ITRDraft)
        .where(ITRDraft.ca_id.is_(None), ITRDraft.status == "pending_ca_review")
        .order_by(ITRDraft.created_at.asc())
        .limit(100)
    )
    itr_result = await db.execute(itr_stmt)
    itr_records = list(itr_result.scalars().all())

    # Enrich ITR with user info
    itr_drafts = []
    for d in itr_records:
        user_stmt = select(User).where(User.id == d.user_id)
        user = (await db.execute(user_stmt)).scalar_one_or_none()
        itr_drafts.append({
            "id": str(d.id),
            "form_type": d.form_type,
            "assessment_year": d.assessment_year,
            "pan": d.pan,
            "user_whatsapp": user.whatsapp_number if user else None,
            "user_name": user.name if user else None,
            "created_at": d.created_at,
        })

    # Available CAs for assignment dropdown
    ca_stmt = (
        select(CAUser)
        .where(CAUser.active.is_(True), CAUser.approved.is_(True))
        .order_by(CAUser.name)
    )
    ca_result = await db.execute(ca_stmt)
    available_cas = list(ca_result.scalars().all())

    return templates.TemplateResponse(
        "admin/ca_queue.html",
        {
            "request": request,
            "title": "Unassigned Filing Queue",
            "gst_filings": gst_filings,
            "itr_drafts": itr_drafts,
            "available_cas": available_cas,
            "admin_token": "",
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/ca/queue/{filing_type}/{filing_id}/assign — Assign CA from queue
# ---------------------------------------------------------------------------


@router.post("/queue/{filing_type}/{filing_id}/assign")
async def ca_queue_assign(
    filing_type: str,
    filing_id: str,
    request: Request,
    admin_token: str = Form(""),
    ca_id: int = Form(...),
    create_client: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Assign a CA to an unassigned GST filing or ITR draft (HTML form)."""
    verify_admin_form_token(admin_token, request)

    from uuid import UUID as _UUID
    fid = _UUID(filing_id)
    should_create_client = create_client == "1"

    # Validate target CA
    ca_stmt = select(CAUser).where(CAUser.id == ca_id)
    ca_result = await db.execute(ca_stmt)
    target_ca = ca_result.scalar_one_or_none()
    if not target_ca or not target_ca.active or not target_ca.approved:
        raise HTTPException(status_code=400, detail="Target CA is not active or not approved")

    user = None

    if filing_type == "gst":
        stmt = select(FilingRecord).where(FilingRecord.id == fid)
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="Filing not found")
        record.ca_id = ca_id
        # Resolve user for client creation
        user_stmt = select(User).where(User.id == record.user_id)
        user = (await db.execute(user_stmt)).scalar_one_or_none()
        gstin = record.gstin
        pan = None

    elif filing_type == "itr":
        stmt = select(ITRDraft).where(ITRDraft.id == fid)
        result = await db.execute(stmt)
        draft = result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        draft.ca_id = ca_id
        user_stmt = select(User).where(User.id == draft.user_id)
        user = (await db.execute(user_stmt)).scalar_one_or_none()
        gstin = None
        pan = draft.pan

    else:
        raise HTTPException(status_code=400, detail="Invalid filing_type")

    # Optionally create BusinessClient
    if should_create_client and user:
        existing_stmt = select(BusinessClient).where(
            BusinessClient.whatsapp_number == user.whatsapp_number
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if not existing:
            new_client = BusinessClient(
                ca_id=ca_id,
                name=user.name or user.whatsapp_number,
                whatsapp_number=user.whatsapp_number,
                gstin=gstin,
                pan=pan,
            )
            db.add(new_client)

    await db.commit()

    log_admin_action(
        f"assign_ca_to_{filing_type}",
        admin_ip=request.client.host if request.client else "",
        details={"filing_id": filing_id, "ca_id": ca_id, "create_client": should_create_client},
    )

    return RedirectResponse(url="/admin/ca/queue", status_code=303)


# ---------------------------------------------------------------------------
# GET  /admin/ca/{ca_id} — CA detail page
# ---------------------------------------------------------------------------


@router.get("/{ca_id}")
async def ca_detail(
    ca_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    # Fetch CA
    stmt = select(CAUser).where(CAUser.id == ca_id)
    result = await db.execute(stmt)
    ca: CAUser | None = result.scalar_one_or_none()
    if ca is None:
        raise HTTPException(status_code=404, detail="CA not found")

    # Fetch clients belonging to this CA
    client_stmt = select(BusinessClient).where(BusinessClient.ca_id == ca_id)
    client_result = await db.execute(client_stmt)
    clients: list[BusinessClient] = list(client_result.scalars().all())

    # Other active+approved CAs for transfer dropdown (exclude current)
    other_stmt = (
        select(CAUser)
        .where(
            CAUser.id != ca_id,
            CAUser.active.is_(True),
            CAUser.approved.is_(True),
        )
        .order_by(CAUser.name)
    )
    other_result = await db.execute(other_stmt)
    other_cas: list[CAUser] = list(other_result.scalars().all())

    pending_gst = await _pending_gst_count(db, ca_id)
    pending_itr = await _pending_itr_count(db, ca_id)

    return templates.TemplateResponse(
        "admin/ca_detail.html",
        {
            "request": request,
            "title": f"CA: {ca.name}",
            "ca": ca,
            "clients": clients,
            "other_cas": other_cas,
            "pending_gst": pending_gst,
            "pending_itr": pending_itr,
            "admin_token": "",  # SECURITY: Never expose ADMIN_API_KEY in HTML
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/ca/{ca_id}/approve — Approve a pending CA
# ---------------------------------------------------------------------------


@router.post("/{ca_id}/approve")
async def ca_approve(
    ca_id: int,
    request: Request,
    admin_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    verify_admin_form_token(admin_token, request)

    stmt = select(CAUser).where(CAUser.id == ca_id)
    result = await db.execute(stmt)
    ca: CAUser | None = result.scalar_one_or_none()
    if ca is None:
        raise HTTPException(status_code=404, detail="CA not found")

    ca.approved = True
    ca.approved_at = datetime.now(timezone.utc)
    await db.commit()

    log_admin_action(
        "approve_ca",
        admin_ip=request.client.host if request.client else "",
        details={"ca_id": ca_id, "ca_email": ca.email},
    )

    return RedirectResponse(url="/admin/ca/pending", status_code=303)


# ---------------------------------------------------------------------------
# POST /admin/ca/{ca_id}/reject — Reject a pending CA
# ---------------------------------------------------------------------------


@router.post("/{ca_id}/reject")
async def ca_reject(
    ca_id: int,
    request: Request,
    admin_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    verify_admin_form_token(admin_token, request)

    stmt = select(CAUser).where(CAUser.id == ca_id)
    result = await db.execute(stmt)
    ca: CAUser | None = result.scalar_one_or_none()
    if ca is None:
        raise HTTPException(status_code=404, detail="CA not found")

    ca.active = False
    await db.commit()

    log_admin_action(
        "reject_ca",
        admin_ip=request.client.host if request.client else "",
        details={"ca_id": ca_id, "ca_email": ca.email},
    )

    return RedirectResponse(url="/admin/ca/pending", status_code=303)


# ---------------------------------------------------------------------------
# POST /admin/ca/{ca_id}/toggle-active — Toggle CA active status
# ---------------------------------------------------------------------------


@router.post("/{ca_id}/toggle-active")
async def ca_toggle_active(
    ca_id: int,
    request: Request,
    admin_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    verify_admin_form_token(admin_token, request)

    stmt = select(CAUser).where(CAUser.id == ca_id)
    result = await db.execute(stmt)
    ca: CAUser | None = result.scalar_one_or_none()
    if ca is None:
        raise HTTPException(status_code=404, detail="CA not found")

    ca.active = not ca.active
    await db.commit()

    log_admin_action(
        "toggle_ca_active",
        admin_ip=request.client.host if request.client else "",
        details={"ca_id": ca_id, "ca_email": ca.email, "new_active": ca.active},
    )

    return RedirectResponse(url=f"/admin/ca/{ca_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /admin/ca/clients/{client_id}/transfer — Transfer client to another CA
# ---------------------------------------------------------------------------


@router.post("/clients/{client_id}/transfer")
async def client_transfer(
    client_id: int,
    request: Request,
    admin_token: str = Form(""),
    to_ca_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    verify_admin_form_token(admin_token, request)

    # Fetch client
    client_stmt = select(BusinessClient).where(BusinessClient.id == client_id)
    client_result = await db.execute(client_stmt)
    client: BusinessClient | None = client_result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # Fetch target CA and verify it is active + approved
    target_stmt = select(CAUser).where(CAUser.id == to_ca_id)
    target_result = await db.execute(target_stmt)
    target_ca: CAUser | None = target_result.scalar_one_or_none()
    if target_ca is None:
        raise HTTPException(status_code=404, detail="Target CA not found")
    if not target_ca.active or not target_ca.approved:
        raise HTTPException(
            status_code=400, detail="Target CA is not active or not approved"
        )

    old_ca_id = client.ca_id
    client.ca_id = to_ca_id
    await db.commit()

    log_admin_action(
        "transfer_client",
        admin_ip=request.client.host if request.client else "",
        details={
            "client_id": client_id,
            "from_ca_id": old_ca_id,
            "to_ca_id": to_ca_id,
        },
    )

    return RedirectResponse(url=f"/admin/ca/{old_ca_id}", status_code=303)
