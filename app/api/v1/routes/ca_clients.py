# app/api/v1/routes/ca_clients.py
"""CA client management endpoints: CRUD, bulk upload, analytics, PDF export."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import Response, StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.domain.services.ca_auth import get_current_ca
from app.domain.services.gstin_pan_validation import (
    is_valid_gstin,
    is_valid_pan,
    is_valid_whatsapp_number,
    normalize_whatsapp_number,
)
from app.domain.services.tax_analytics import (
    aggregate_invoices,
    detect_anomalies_dynamic as detect_anomalies,
    generate_ai_insights,
    get_filing_deadlines,
)
from app.infrastructure.audit import log_ca_action
from app.infrastructure.db.models import BusinessClient, CAUser, Invoice, User
from app.infrastructure.db.repositories.ca_repository import BusinessClientRepository

from app.api.v1.envelope import ok, error, paginated
from app.api.v1.schemas.ca import (
    AnalyticsOut,
    BulkUploadResult,
    BulkUploadRow,
    ClientCreate,
    ClientOut,
    ClientUpdate,
    InsightsOut,
)

logger = logging.getLogger("api.v1.ca_clients")

router = APIRouter(prefix="/ca/clients", tags=["CA Clients"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_to_out(c: BusinessClient) -> dict:
    """Convert an ORM BusinessClient to a ClientOut dict."""
    return ClientOut(
        id=c.id,
        name=c.name,
        gstin=c.gstin,
        pan=c.pan,
        whatsapp_number=c.whatsapp_number,
        email=c.email,
        business_type=c.business_type,
        address=c.address,
        state_code=c.state_code,
        notes=c.notes,
        status=c.status,
        ca_id=c.ca_id,
        # Segment fields (Phase 4)
        segment=getattr(c, "segment", "small"),
        annual_turnover=float(c.annual_turnover) if getattr(c, "annual_turnover", None) else None,
        monthly_invoice_volume=getattr(c, "monthly_invoice_volume", None),
        gstin_count=getattr(c, "gstin_count", 1),
        is_exporter=getattr(c, "is_exporter", False),
        created_at=c.created_at,
        updated_at=c.updated_at,
    ).model_dump()


async def _get_client_or_404(
    client_id: int, ca: CAUser, db: AsyncSession
) -> BusinessClient:
    repo = BusinessClientRepository(db)
    client = await repo.get_by_id(client_id)
    if client is None or client.ca_id != ca.id:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _validate_client_fields(
    raw_wa: str | None,
    gstin: str | None,
    pan: str | None,
) -> tuple[str | None, list[str]]:
    """Validate and normalize client fields. Returns (normalized_wa, errors)."""
    errors: list[str] = []
    normalized_wa: str | None = None

    if raw_wa:
        normalized_wa = normalize_whatsapp_number(raw_wa)
        if normalized_wa is None:
            errors.append(
                "Invalid WhatsApp number. Enter 10-digit mobile (e.g. 9876543210) "
                "or with country code (e.g. 919876543210)."
            )
        elif not is_valid_whatsapp_number(normalized_wa):
            errors.append(
                "WhatsApp number must be a valid Indian mobile number (starting with 6-9)."
            )
    if gstin and not is_valid_gstin(gstin):
        errors.append("Invalid GSTIN format. Expected 15-character alphanumeric (e.g. 22AAAAA0000A1Z5).")
    if pan and not is_valid_pan(pan):
        errors.append("Invalid PAN format. Expected 10-character (e.g. AAAAA0000A).")

    return normalized_wa, errors


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=dict)
async def list_clients(
    q: str = Query("", description="Search by name, GSTIN, PAN, or WhatsApp"),
    limit: int = Query(50, ge=1, le=200, description="Max items"),
    offset: int = Query(0, ge=0, description="Skip N items"),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """List the authenticated CA's clients with optional search and pagination."""
    repo = BusinessClientRepository(db)

    if q.strip():
        all_clients = await repo.search(ca.id, q.strip())
    else:
        all_clients = await repo.list_for_ca(ca.id)

    total = len(all_clients)
    page = all_clients[offset : offset + limit]

    return paginated(
        items=[_client_to_out(c) for c in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Create a new business client for the authenticated CA."""
    repo = BusinessClientRepository(db)

    clean_gstin = body.gstin.strip().upper() if body.gstin else None
    clean_pan = body.pan.strip().upper() if body.pan else None
    raw_wa = body.whatsapp_number.strip() if body.whatsapp_number else None

    normalized_wa, errors = _validate_client_fields(raw_wa, clean_gstin, clean_pan)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    # Build extra segment kwargs if provided
    segment_kwargs: dict = {}
    if body.segment is not None:
        segment_kwargs["segment"] = body.segment
    if body.annual_turnover is not None:
        segment_kwargs["annual_turnover"] = body.annual_turnover
    if body.monthly_invoice_volume is not None:
        segment_kwargs["monthly_invoice_volume"] = body.monthly_invoice_volume

    try:
        client = await repo.create(
            ca_id=ca.id,
            name=body.name.strip(),
            gstin=clean_gstin,
            whatsapp_number=normalized_wa,
            pan=clean_pan,
            email=body.email.strip().lower() if body.email else None,
            business_type=body.business_type.strip() if body.business_type else None,
            address=body.address.strip() if body.address else None,
            state_code=body.state_code.strip() if body.state_code else None,
            notes=body.notes.strip() if body.notes else None,
            **segment_kwargs,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This WhatsApp number is already registered with another CA.",
        )

    log_ca_action(
        "create_client",
        ca_id=ca.id,
        ca_email=ca.email,
        client_id=client.id,
        details={"name": body.name.strip()},
    )

    return ok(data=_client_to_out(client), message="Client created")


@router.get("/bulk-upload/template")
async def bulk_upload_template():
    """Download a CSV template with the expected column headers."""
    content = "name,whatsapp_number,gstin,pan,email,business_type\n"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=client_template.csv"},
    )


@router.post("/bulk-upload", response_model=dict)
async def bulk_upload(
    file: UploadFile = File(...),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Upload a CSV file to create multiple clients in bulk."""
    repo = BusinessClientRepository(db)

    added: list[BulkUploadRow] = []
    skipped: list[BulkUploadRow] = []
    failed: list[BulkUploadRow] = []

    try:
        raw = await file.read()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the file. Please upload a valid UTF-8 CSV.")

    for row_num, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        raw_wa = (row.get("whatsapp_number") or "").strip()
        raw_gstin = (row.get("gstin") or "").strip().upper()
        raw_pan = (row.get("pan") or "").strip().upper()
        raw_email = (row.get("email") or "").strip().lower()
        raw_btype = (row.get("business_type") or "").strip()

        row_errors: list[str] = []
        if not name:
            row_errors.append("name is required")

        normalized_wa: str | None = None
        if raw_wa:
            normalized_wa = normalize_whatsapp_number(raw_wa)
            if normalized_wa is None:
                row_errors.append("invalid WhatsApp number")
        if raw_gstin and not is_valid_gstin(raw_gstin):
            row_errors.append("invalid GSTIN")
        if raw_pan and not is_valid_pan(raw_pan):
            row_errors.append("invalid PAN")

        if row_errors:
            failed.append(BulkUploadRow(row=row_num, name=name or "(empty)", reason="; ".join(row_errors)))
            continue

        # Check duplicate WhatsApp
        if normalized_wa:
            existing = await repo.get_by_whatsapp(normalized_wa)
            if existing:
                skipped.append(
                    BulkUploadRow(row=row_num, name=name, reason=f"WhatsApp {normalized_wa} already registered")
                )
                continue

        try:
            client = await repo.create(
                ca_id=ca.id,
                name=name,
                gstin=raw_gstin or None,
                whatsapp_number=normalized_wa,
                pan=raw_pan or None,
                email=raw_email or None,
                business_type=raw_btype or None,
            )
            added.append(BulkUploadRow(row=row_num, name=name, client_id=client.id))
        except IntegrityError:
            await db.rollback()
            skipped.append(BulkUploadRow(row=row_num, name=name, reason="Duplicate entry"))
        except Exception as exc:
            failed.append(BulkUploadRow(row=row_num, name=name, reason=str(exc)))

    result = BulkUploadResult(
        added_count=len(added),
        skipped_count=len(skipped),
        failed_count=len(failed),
        added=added,
        skipped=skipped,
        failed=failed,
    )

    return ok(data=result.model_dump(), message=f"{len(added)} added, {len(skipped)} skipped, {len(failed)} failed")


@router.get("/{client_id}", response_model=dict)
async def get_client(
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Get a single client by ID (must belong to the authenticated CA)."""
    client = await _get_client_or_404(client_id, ca, db)
    return ok(data=_client_to_out(client))


@router.put("/{client_id}", response_model=dict)
async def update_client(
    client_id: int,
    body: ClientUpdate,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing client. Only provided fields are changed."""
    client = await _get_client_or_404(client_id, ca, db)
    repo = BusinessClientRepository(db)

    # Build update kwargs from non-None fields
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name.strip()

    raw_wa = body.whatsapp_number
    clean_gstin = body.gstin.strip().upper() if body.gstin else body.gstin
    clean_pan = body.pan.strip().upper() if body.pan else body.pan

    # Validate changed fields
    errors: list[str] = []
    if raw_wa is not None:
        if raw_wa == "":
            updates["whatsapp_number"] = None
        else:
            nw = normalize_whatsapp_number(raw_wa)
            if nw is None:
                errors.append("Invalid WhatsApp number.")
            elif not is_valid_whatsapp_number(nw):
                errors.append("WhatsApp number must be a valid Indian mobile (starting with 6-9).")
            else:
                updates["whatsapp_number"] = nw
    if clean_gstin is not None:
        if clean_gstin == "":
            updates["gstin"] = None
        elif not is_valid_gstin(clean_gstin):
            errors.append("Invalid GSTIN format.")
        else:
            updates["gstin"] = clean_gstin
    if clean_pan is not None:
        if clean_pan == "":
            updates["pan"] = None
        elif not is_valid_pan(clean_pan):
            errors.append("Invalid PAN format.")
        else:
            updates["pan"] = clean_pan

    if body.email is not None:
        updates["email"] = body.email.strip().lower() if body.email else None
    if body.business_type is not None:
        updates["business_type"] = body.business_type.strip() or None
    if body.address is not None:
        updates["address"] = body.address.strip() or None
    if body.state_code is not None:
        updates["state_code"] = body.state_code.strip() or None
    if body.notes is not None:
        updates["notes"] = body.notes.strip() or None

    # Segment fields (Phase 4)
    if body.segment is not None:
        if body.segment not in ("small", "medium", "enterprise"):
            errors.append("Invalid segment. Use small/medium/enterprise.")
        else:
            updates["segment"] = body.segment
    if body.annual_turnover is not None:
        updates["annual_turnover"] = body.annual_turnover
    if body.monthly_invoice_volume is not None:
        updates["monthly_invoice_volume"] = body.monthly_invoice_volume

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    try:
        updated = await repo.update(client.id, **updates)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This WhatsApp number is already registered with another CA.",
        )

    log_ca_action(
        "update_client",
        ca_id=ca.id,
        ca_email=ca.email,
        client_id=client.id,
        details={"updates": list(updates.keys())},
    )

    return ok(data=_client_to_out(updated), message="Client updated")


@router.delete("/{client_id}", response_model=dict)
async def deactivate_client(
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deactivate a client (sets status to inactive)."""
    client = await _get_client_or_404(client_id, ca, db)
    repo = BusinessClientRepository(db)
    await repo.deactivate(client.id)

    log_ca_action(
        "deactivate_client",
        ca_id=ca.id,
        ca_email=ca.email,
        client_id=client.id,
        details={"name": client.name},
    )

    return ok(message="Client deactivated")


# ---------------------------------------------------------------------------
# Analytics & Insights
# ---------------------------------------------------------------------------

@router.get("/{client_id}/analytics", response_model=dict)
async def client_analytics(
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Return tax analytics for a client: invoice summary, anomalies, deadlines."""
    client = await _get_client_or_404(client_id, ca, db)

    # Fetch invoices for this client's WhatsApp user
    invoices = []
    if client.whatsapp_number:
        user_stmt = select(User).where(User.whatsapp_number == client.whatsapp_number)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if user:
            inv_stmt = (
                select(Invoice)
                .where(Invoice.user_id == user.id)
                .order_by(Invoice.invoice_date.desc())
            )
            inv_result = await db.execute(inv_stmt)
            invoices = list(inv_result.scalars().all())

    summary = aggregate_invoices(invoices)
    anomalies = await detect_anomalies(invoices)
    deadlines = get_filing_deadlines()

    return ok(
        data=AnalyticsOut(
            summary=summary,
            anomalies=anomalies,
            deadlines=deadlines,
        ).model_dump(),
    )


@router.get("/{client_id}/insights", response_model=dict)
async def client_insights(
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Return AI-generated insights for a client's tax data."""
    client = await _get_client_or_404(client_id, ca, db)

    invoices = []
    if client.whatsapp_number:
        user_stmt = select(User).where(User.whatsapp_number == client.whatsapp_number)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if user:
            inv_stmt = (
                select(Invoice)
                .where(Invoice.user_id == user.id)
                .order_by(Invoice.invoice_date.desc())
            )
            inv_result = await db.execute(inv_stmt)
            invoices = list(inv_result.scalars().all())

    summary = aggregate_invoices(invoices)
    anomalies = await detect_anomalies(invoices)
    text = await generate_ai_insights(summary, anomalies) if invoices else "No invoice data available for insights."

    return ok(
        data=InsightsOut(
            text=text,
            generated_at=datetime.now(timezone.utc),
        ).model_dump(),
    )


@router.get("/{client_id}/invoices.pdf")
async def client_invoices_pdf(
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Download a PDF report of all invoices for this client."""
    client = await _get_client_or_404(client_id, ca, db)

    invoices = []
    if client.whatsapp_number:
        user_stmt = select(User).where(User.whatsapp_number == client.whatsapp_number)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if user:
            inv_stmt = (
                select(Invoice)
                .where(Invoice.user_id == user.id)
                .order_by(Invoice.invoice_date.desc())
            )
            inv_result = await db.execute(inv_stmt)
            invoices = list(inv_result.scalars().all())

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 50, f"Invoice Report: {client.name}")
    c.setFont("Helvetica", 10)
    y = h - 80

    for inv in invoices:
        if y < 60:
            c.showPage()
            y = h - 50
        line = f"{inv.invoice_date}  |  Taxable: {inv.taxable_value:,.2f}  |  Tax: {inv.tax_amount:,.2f}"
        c.drawString(50, y, line)
        y -= 18

    if not invoices:
        c.drawString(50, y, "No invoices found.")

    c.save()
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{client.name}_invoices.pdf"'},
    )
