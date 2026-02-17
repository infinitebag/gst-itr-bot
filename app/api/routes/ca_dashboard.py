# app/api/routes/ca_dashboard.py
"""
CA Dashboard routes — client management, analytics, insights, deadlines, PDF export.
All routes require JWT authentication via ``get_current_ca``.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
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
from app.infrastructure.audit import log_ca_action
from app.domain.services.tax_analytics import (
    aggregate_invoices,
    detect_anomalies_dynamic as detect_anomalies,
    generate_ai_insights,
    get_filing_deadlines,
)
from app.infrastructure.db.models import BusinessClient, CAUser, Invoice, ITRDraft, User
from app.infrastructure.db.repositories.ca_repository import (
    BusinessClientRepository,
)

router = APIRouter(prefix="/ca", tags=["ca-dashboard"])
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_client_or_404(
    client_id: int,
    ca: CAUser,
    db: AsyncSession,
) -> BusinessClient:
    """Fetch client and ensure it belongs to the current CA."""
    repo = BusinessClientRepository(db)
    client = await repo.get_by_id(client_id)
    if client is None or client.ca_id != ca.id:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _get_client_invoices(
    client: BusinessClient,
    db: AsyncSession,
    start: date | None = None,
    end: date | None = None,
) -> list[Invoice]:
    """Fetch invoices for a client via whatsapp_number → User → invoices."""
    if not client.whatsapp_number:
        return []

    user_stmt = select(User).where(User.whatsapp_number == client.whatsapp_number)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    if user is None:
        return []

    stmt = select(Invoice).where(Invoice.user_id == user.id)
    if start:
        stmt = stmt.where(Invoice.invoice_date >= start)
    if end:
        stmt = stmt.where(Invoice.invoice_date <= end)
    stmt = stmt.order_by(Invoice.invoice_date.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Dashboard Home
# ---------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard overview: total clients, pending filings, recent invoices."""
    client_repo = BusinessClientRepository(db)
    clients = await client_repo.list_for_ca(ca.id)
    active_clients = [c for c in clients if c.status == "active"]

    # Count total invoices across all clients (single query via JOIN)
    wa_numbers = [c.whatsapp_number for c in active_clients if c.whatsapp_number]
    total_invoices = 0
    recent_invoices: list[dict[str, Any]] = []

    if wa_numbers:
        # Total invoice count across all clients
        count_stmt = (
            select(func.count(Invoice.id))
            .join(User, User.id == Invoice.user_id)
            .where(User.whatsapp_number.in_(wa_numbers))
        )
        count_result = await db.execute(count_stmt)
        total_invoices = count_result.scalar_one() or 0

        # Build a name lookup for clients
        client_name_map = {c.whatsapp_number: c.name for c in active_clients if c.whatsapp_number}

        # Recent invoices (single query with JOIN)
        recent_stmt = (
            select(Invoice, User.whatsapp_number)
            .join(User, User.id == Invoice.user_id)
            .where(User.whatsapp_number.in_(wa_numbers))
            .order_by(Invoice.created_at.desc())
            .limit(10)
        )
        recent_result = await db.execute(recent_stmt)
        for inv, wa_num in recent_result.all():
            recent_invoices.append(
                {
                    "client_name": client_name_map.get(wa_num, "Unknown"),
                    "invoice_number": inv.invoice_number,
                    "invoice_date": inv.invoice_date,
                    "total_amount": float(inv.total_amount) if inv.total_amount else 0,
                    "created_at": inv.created_at,
                }
            )

    # Filing deadlines
    deadlines = get_filing_deadlines()
    overdue = [d for d in deadlines if d.status == "overdue"]

    # Pending ITR reviews count
    pending_itr_stmt = (
        select(func.count(ITRDraft.id))
        .where(
            ITRDraft.ca_id == ca.id,
            ITRDraft.status == "pending_ca_review",
        )
    )
    pending_itr_result = await db.execute(pending_itr_stmt)
    pending_itr_count = pending_itr_result.scalar_one() or 0

    # Pending GST reviews count
    from app.infrastructure.db.models import FilingRecord
    pending_gst_stmt = (
        select(func.count(FilingRecord.id))
        .where(
            FilingRecord.ca_id == ca.id,
            FilingRecord.filing_type == "GST",
            FilingRecord.status == "pending_ca_review",
        )
    )
    pending_gst_result = await db.execute(pending_gst_stmt)
    pending_gst_count = pending_gst_result.scalar_one() or 0

    return templates.TemplateResponse(
        "ca/dashboard.html",
        {
            "request": request,
            "title": "CA Dashboard",
            "ca": ca,
            "total_clients": len(active_clients),
            "total_invoices": total_invoices,
            "overdue_count": len(overdue),
            "pending_itr_count": pending_itr_count,
            "pending_gst_count": pending_gst_count,
            "recent_invoices": recent_invoices,
            "deadlines": deadlines[:5],
        },
    )


# ---------------------------------------------------------------------------
# Client List
# ---------------------------------------------------------------------------

@router.get("/clients", response_class=HTMLResponse)
async def client_list(
    request: Request,
    q: str = Query("", description="Search query"),
    added: int = Query(0, description="Number of clients just added (for success banner)"),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """List all clients for the current CA with optional search."""
    repo = BusinessClientRepository(db)

    if q.strip():
        clients = await repo.search(ca.id, q.strip())
    else:
        clients = await repo.list_for_ca(ca.id)

    # Enrich with invoice counts
    rows: list[dict[str, Any]] = []
    for c in clients:
        inv_count = 0
        last_invoice = None
        if c.whatsapp_number:
            inv_stmt = select(
                func.count(Invoice.id),
                func.max(Invoice.invoice_date),
            ).where(Invoice.receiver_gstin == c.gstin)
            inv_result = await db.execute(inv_stmt)
            inv_count, last_invoice = inv_result.one()

        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "gstin": c.gstin,
                "pan": c.pan,
                "whatsapp_number": c.whatsapp_number,
                "business_type": c.business_type,
                "status": c.status,
                "invoice_count": int(inv_count or 0),
                "last_invoice": last_invoice.isoformat() if last_invoice else None,
            }
        )

    return templates.TemplateResponse(
        "ca/clients.html",
        {
            "request": request,
            "title": "My Clients",
            "ca": ca,
            "clients": rows,
            "search_query": q,
            "added_count": added,
        },
    )


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------

@router.get("/clients/new", response_class=HTMLResponse)
async def new_client_form(
    request: Request,
    ca: CAUser = Depends(get_current_ca),
):
    """Render the add-client form."""
    return templates.TemplateResponse(
        "ca/client_form.html",
        {
            "request": request,
            "title": "Add Client",
            "ca": ca,
            "client": None,
            "error": None,
        },
    )


# ---------------------------------------------------------------------------
# Bulk CSV Upload
# ---------------------------------------------------------------------------


@router.get("/clients/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_form(
    request: Request,
    ca: CAUser = Depends(get_current_ca),
):
    """Render the CSV bulk-upload page."""
    return templates.TemplateResponse(
        "ca/client_bulk_upload.html",
        {"request": request, "title": "Bulk Upload Clients", "ca": ca},
    )


@router.get("/clients/bulk-upload/template")
async def bulk_upload_template():
    """Download a CSV template with the expected column headers."""
    content = "name,whatsapp_number,gstin,pan,email,business_type\n"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=client_template.csv"},
    )


@router.post("/clients/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_process(
    request: Request,
    file: UploadFile = Form(...),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Process an uploaded CSV and create clients in bulk."""
    repo = BusinessClientRepository(db)

    added: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    # Read and decode CSV
    try:
        raw = await file.read()
        text = raw.decode("utf-8-sig")  # handle BOM from Excel
        reader = csv.DictReader(io.StringIO(text))
    except Exception:
        return templates.TemplateResponse(
            "ca/client_bulk_upload.html",
            {"request": request, "title": "Bulk Upload Clients", "ca": ca,
             "error": "Could not read the file. Please upload a valid UTF-8 CSV."},
            status_code=400,
        )

    for row_num, row in enumerate(reader, start=2):  # row 1 is header
        name = (row.get("name") or "").strip()
        raw_wa = (row.get("whatsapp_number") or "").strip()
        raw_gstin = (row.get("gstin") or "").strip().upper()
        raw_pan = (row.get("pan") or "").strip().upper()
        raw_email = (row.get("email") or "").strip().lower()
        raw_btype = (row.get("business_type") or "").strip()

        # --- Validate ---
        row_errors: list[str] = []
        if not name:
            row_errors.append("name is required")

        normalized_wa: str | None = None
        if raw_wa:
            normalized_wa = normalize_whatsapp_number(raw_wa)
            if normalized_wa is None:
                row_errors.append("invalid WhatsApp number")
            elif not is_valid_whatsapp_number(normalized_wa):
                row_errors.append("WhatsApp must be valid Indian mobile")
        if raw_gstin and not is_valid_gstin(raw_gstin):
            row_errors.append("invalid GSTIN")
        if raw_pan and not is_valid_pan(raw_pan):
            row_errors.append("invalid PAN")

        if row_errors:
            failed.append({"row": str(row_num), "name": name or "(empty)", "reason": "; ".join(row_errors)})
            continue

        # --- Duplicate check ---
        if normalized_wa:
            existing = await repo.get_by_whatsapp(normalized_wa)
            if existing:
                skipped.append({"row": str(row_num), "name": name, "reason": f"WhatsApp {normalized_wa} already registered"})
                continue

        # --- Create ---
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
            added.append({"row": str(row_num), "name": name, "id": str(client.id)})
        except IntegrityError:
            await db.rollback()
            skipped.append({"row": str(row_num), "name": name, "reason": "duplicate (WhatsApp or GSTIN conflict)"})
        except Exception:
            failed.append({"row": str(row_num), "name": name, "reason": "unexpected error"})

    if added:
        for a in added:
            log_ca_action("bulk_create_client", ca_id=ca.id, ca_email=ca.email, client_id=int(a["id"]), details={"name": a["name"]})

    return templates.TemplateResponse(
        "ca/client_bulk_results.html",
        {
            "request": request,
            "title": "Bulk Upload Results",
            "ca": ca,
            "added": added,
            "skipped": skipped,
            "failed": failed,
        },
    )


@router.post("/clients")
async def create_client(
    request: Request,
    name: str = Form(...),
    gstin: str = Form(""),
    whatsapp_number: str = Form(""),
    pan: str = Form(""),
    email: str = Form(""),
    business_type: str = Form(""),
    address: str = Form(""),
    state_code: str = Form(""),
    notes: str = Form(""),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Create a new business client."""
    repo = BusinessClientRepository(db)

    # --- Normalize & validate inputs ---
    clean_gstin = gstin.strip().upper() or None
    clean_pan = pan.strip().upper() or None
    raw_wa = whatsapp_number.strip()
    normalized_wa: str | None = None

    errors: list[str] = []
    if raw_wa:
        normalized_wa = normalize_whatsapp_number(raw_wa)
        if normalized_wa is None:
            errors.append("Invalid WhatsApp number. Enter 10-digit mobile (e.g. 9876543210) or with country code (e.g. 919876543210).")
        elif not is_valid_whatsapp_number(normalized_wa):
            errors.append("WhatsApp number must be a valid Indian mobile number (starting with 6-9).")
    if clean_gstin and not is_valid_gstin(clean_gstin):
        errors.append("Invalid GSTIN format. Expected 15-character alphanumeric (e.g. 22AAAAA0000A1Z5).")
    if clean_pan and not is_valid_pan(clean_pan):
        errors.append("Invalid PAN format. Expected 10-character (e.g. AAAAA0000A).")
    if errors:
        return templates.TemplateResponse(
            "ca/client_form.html",
            {"request": request, "title": "Add Client", "ca": ca, "client": None, "error": "\n".join(errors)},
            status_code=400,
        )

    # Eagerly capture CA attributes before DB writes — after rollback the
    # async session expires ORM objects and lazy-loading fails.
    ca_info = SimpleNamespace(name=ca.name, id=ca.id, email=ca.email)

    try:
        client = await repo.create(
            ca_id=ca_info.id,
            name=name.strip(),
            gstin=clean_gstin,
            whatsapp_number=normalized_wa,
            pan=clean_pan,
            email=email.strip().lower() or None,
            business_type=business_type.strip() or None,
            address=address.strip() or None,
            state_code=state_code.strip() or None,
            notes=notes.strip() or None,
        )
        log_ca_action("create_client", ca_id=ca_info.id, ca_email=ca_info.email, client_id=client.id, details={"name": name.strip()})
        return RedirectResponse(url=f"/ca/clients/{client.id}", status_code=303)
    except IntegrityError:
        await db.rollback()
        return templates.TemplateResponse(
            "ca/client_form.html",
            {"request": request, "title": "Add Client", "ca": ca_info, "client": None,
             "error": "This WhatsApp number is already registered with another CA."},
            status_code=400,
        )
    except Exception:
        return templates.TemplateResponse(
            "ca/client_form.html",
            {"request": request, "title": "Add Client", "ca": ca_info, "client": None,
             "error": "An unexpected error occurred. Please try again."},
            status_code=400,
        )


@router.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_detail(
    request: Request,
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Client profile with invoices."""
    client = await _get_client_or_404(client_id, ca, db)
    invoices = await _get_client_invoices(client, db)

    return templates.TemplateResponse(
        "ca/client_detail.html",
        {
            "request": request,
            "title": f"Client: {client.name}",
            "ca": ca,
            "client": client,
            "invoices": invoices,
        },
    )


@router.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def edit_client_form(
    request: Request,
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Render the edit-client form."""
    client = await _get_client_or_404(client_id, ca, db)

    return templates.TemplateResponse(
        "ca/client_form.html",
        {
            "request": request,
            "title": f"Edit: {client.name}",
            "ca": ca,
            "client": client,
            "error": None,
        },
    )


@router.post("/clients/{client_id}")
async def update_client(
    request: Request,
    client_id: int,
    name: str = Form(...),
    gstin: str = Form(""),
    whatsapp_number: str = Form(""),
    pan: str = Form(""),
    email: str = Form(""),
    business_type: str = Form(""),
    address: str = Form(""),
    state_code: str = Form(""),
    notes: str = Form(""),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing client."""
    client = await _get_client_or_404(client_id, ca, db)
    repo = BusinessClientRepository(db)

    # --- Normalize & validate inputs ---
    clean_gstin = gstin.strip().upper() or None
    clean_pan = pan.strip().upper() or None
    raw_wa = whatsapp_number.strip()
    normalized_wa: str | None = None

    errors: list[str] = []
    if raw_wa:
        normalized_wa = normalize_whatsapp_number(raw_wa)
        if normalized_wa is None:
            errors.append("Invalid WhatsApp number. Enter 10-digit mobile (e.g. 9876543210) or with country code (e.g. 919876543210).")
        elif not is_valid_whatsapp_number(normalized_wa):
            errors.append("WhatsApp number must be a valid Indian mobile number (starting with 6-9).")
    if clean_gstin and not is_valid_gstin(clean_gstin):
        errors.append("Invalid GSTIN format. Expected 15-character alphanumeric (e.g. 22AAAAA0000A1Z5).")
    if clean_pan and not is_valid_pan(clean_pan):
        errors.append("Invalid PAN format. Expected 10-character (e.g. AAAAA0000A).")
    if errors:
        return templates.TemplateResponse(
            "ca/client_form.html",
            {"request": request, "title": f"Edit: {client.name}", "ca": ca, "client": client, "error": "\n".join(errors)},
            status_code=400,
        )

    # Eagerly capture attributes — after rollback the async session
    # expires ORM objects and lazy-loading fails.
    ca_info = SimpleNamespace(name=ca.name, id=ca.id, email=ca.email)
    client_name = client.name
    client_snap = SimpleNamespace(
        id=client.id, name=client.name, gstin=client.gstin, pan=client.pan,
        whatsapp_number=client.whatsapp_number, business_type=client.business_type,
        email=client.email, address=client.address, state_code=client.state_code,
        notes=client.notes,
    )

    try:
        await repo.update(
            client.id,
            name=name.strip(),
            gstin=clean_gstin,
            whatsapp_number=normalized_wa,
            pan=clean_pan,
            email=email.strip().lower() or None,
            business_type=business_type.strip() or None,
            address=address.strip() or None,
            state_code=state_code.strip() or None,
            notes=notes.strip() or None,
        )
        log_ca_action("update_client", ca_id=ca_info.id, ca_email=ca_info.email, client_id=client.id, details={"name": name.strip()})
        return RedirectResponse(url=f"/ca/clients/{client.id}", status_code=303)
    except IntegrityError:
        await db.rollback()
        return templates.TemplateResponse(
            "ca/client_form.html",
            {"request": request, "title": f"Edit: {client_name}", "ca": ca_info, "client": client_snap,
             "error": "This WhatsApp number is already registered with another CA."},
            status_code=400,
        )
    except Exception:
        return templates.TemplateResponse(
            "ca/client_form.html",
            {"request": request, "title": f"Edit: {client_name}", "ca": ca_info, "client": client_snap,
             "error": "An unexpected error occurred. Please try again."},
            status_code=400,
        )


@router.post("/clients/{client_id}/deactivate")
async def deactivate_client(
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (deactivate) a client."""
    client = await _get_client_or_404(client_id, ca, db)
    repo = BusinessClientRepository(db)
    await repo.deactivate(client.id)
    log_ca_action("deactivate_client", ca_id=ca.id, ca_email=ca.email, client_id=client.id)
    return RedirectResponse(url="/ca/clients", status_code=303)


# ---------------------------------------------------------------------------
# Client Analytics
# ---------------------------------------------------------------------------

@router.get("/clients/{client_id}/analytics", response_class=HTMLResponse)
async def client_analytics(
    request: Request,
    client_id: int,
    period_start: str = Query("", description="YYYY-MM-DD"),
    period_end: str = Query("", description="YYYY-MM-DD"),
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Tax analytics for a specific client."""
    client = await _get_client_or_404(client_id, ca, db)

    # Default to last 12 months
    end = date.today()
    start = end - timedelta(days=365)
    if period_start:
        try:
            start = date.fromisoformat(period_start)
        except ValueError:
            pass
    if period_end:
        try:
            end = date.fromisoformat(period_end)
        except ValueError:
            pass

    invoices = await _get_client_invoices(client, db, start=start, end=end)

    summary = None
    anomalies = None
    if invoices:
        invoice_dicts = [
            {
                "invoice_number": inv.invoice_number,
                "invoice_date": inv.invoice_date,
                "supplier_gstin": inv.supplier_gstin,
                "receiver_gstin": inv.receiver_gstin,
                "taxable_value": float(inv.taxable_value) if inv.taxable_value else 0,
                "tax_amount": float(inv.tax_amount) if inv.tax_amount else 0,
                "total_amount": float(inv.total_amount) if inv.total_amount else 0,
                "cgst_amount": float(inv.cgst_amount) if inv.cgst_amount else 0,
                "sgst_amount": float(inv.sgst_amount) if inv.sgst_amount else 0,
                "igst_amount": float(inv.igst_amount) if inv.igst_amount else 0,
                "tax_rate": float(inv.tax_rate) if inv.tax_rate else 0,
                "place_of_supply": inv.place_of_supply,
            }
            for inv in invoices
        ]
        summary = aggregate_invoices(invoice_dicts)
        anomalies = await detect_anomalies(invoice_dicts)

    return templates.TemplateResponse(
        "ca/client_analytics.html",
        {
            "request": request,
            "title": f"Analytics: {client.name}",
            "ca": ca,
            "client": client,
            "summary": summary,
            "anomalies": anomalies,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "invoice_count": len(invoices),
        },
    )


# ---------------------------------------------------------------------------
# Client AI Insights
# ---------------------------------------------------------------------------

@router.get("/clients/{client_id}/insights", response_class=HTMLResponse)
async def client_insights(
    request: Request,
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """AI-powered tax insights for a specific client."""
    client = await _get_client_or_404(client_id, ca, db)

    end = date.today()
    start = end - timedelta(days=365)
    invoices = await _get_client_invoices(client, db, start=start, end=end)

    ai_insights = "No invoices found for this client yet."
    summary = None
    anomalies = None

    if invoices:
        invoice_dicts = [
            {
                "invoice_number": inv.invoice_number,
                "invoice_date": inv.invoice_date,
                "supplier_gstin": inv.supplier_gstin,
                "receiver_gstin": inv.receiver_gstin,
                "taxable_value": float(inv.taxable_value) if inv.taxable_value else 0,
                "tax_amount": float(inv.tax_amount) if inv.tax_amount else 0,
                "total_amount": float(inv.total_amount) if inv.total_amount else 0,
                "cgst_amount": float(inv.cgst_amount) if inv.cgst_amount else 0,
                "sgst_amount": float(inv.sgst_amount) if inv.sgst_amount else 0,
                "igst_amount": float(inv.igst_amount) if inv.igst_amount else 0,
                "tax_rate": float(inv.tax_rate) if inv.tax_rate else 0,
                "place_of_supply": inv.place_of_supply,
            }
            for inv in invoices
        ]
        summary = aggregate_invoices(invoice_dicts)
        anomalies = await detect_anomalies(invoice_dicts)
        deadlines = get_filing_deadlines()
        ai_insights = await generate_ai_insights(summary, anomalies, deadlines, "en")

    return templates.TemplateResponse(
        "ca/client_insights.html",
        {
            "request": request,
            "title": f"AI Insights: {client.name}",
            "ca": ca,
            "client": client,
            "insights": ai_insights,
            "summary": summary,
            "anomalies": anomalies,
        },
    )


# ---------------------------------------------------------------------------
# Filing Deadlines
# ---------------------------------------------------------------------------

@router.get("/deadlines", response_class=HTMLResponse)
async def deadlines_page(
    request: Request,
    ca: CAUser = Depends(get_current_ca),
):
    """Show all upcoming GST/ITR filing deadlines."""
    all_deadlines = get_filing_deadlines()

    return templates.TemplateResponse(
        "ca/deadlines.html",
        {
            "request": request,
            "title": "Filing Deadlines",
            "ca": ca,
            "deadlines": all_deadlines,
        },
    )


# ---------------------------------------------------------------------------
# Client Invoice PDF Export
# ---------------------------------------------------------------------------

@router.get("/clients/{client_id}/invoices.pdf")
async def client_invoices_pdf(
    client_id: int,
    ca: CAUser = Depends(get_current_ca),
    db: AsyncSession = Depends(get_db),
):
    """Export all invoices for a client as a PDF."""
    client = await _get_client_or_404(client_id, ca, db)
    invoices = await _get_client_invoices(client, db)

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    def line(text: str, step: int = 16):
        nonlocal y
        if y < 60:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica", 10)
        p.drawString(50, y, text)
        y -= step

    def fmt(v):
        return f"{float(v):,.2f}" if v is not None else "-"

    # Header
    p.setFont("Helvetica-Bold", 16)
    line(f"Invoice Report: {client.name}", step=24)

    p.setFont("Helvetica", 11)
    line(f"GSTIN: {client.gstin or '-'}")
    line(f"PAN: {client.pan or '-'}")
    line(f"WhatsApp: {client.whatsapp_number or '-'}")
    line(f"Total Invoices: {len(invoices)}")
    line(f"Generated: {date.today().isoformat()}")
    line("", step=12)

    if not invoices:
        line("No invoices found for this client.")
    else:
        # Table header
        p.setFont("Helvetica-Bold", 9)
        line(
            f"{'No.':<5} {'Invoice #':<18} {'Date':<12} "
            f"{'Taxable':>12} {'Tax':>12} {'Total':>12}"
        )
        p.setFont("Helvetica", 9)
        line("-" * 80, step=12)

        for i, inv in enumerate(invoices, 1):
            inv_date = inv.invoice_date.isoformat() if inv.invoice_date else "-"
            line(
                f"{i:<5} {(inv.invoice_number or '-'):<18} {inv_date:<12} "
                f"{fmt(inv.taxable_value):>12} {fmt(inv.tax_amount):>12} "
                f"{fmt(inv.total_amount):>12}"
            )

        # Totals
        line("", step=8)
        line("-" * 80, step=12)
        p.setFont("Helvetica-Bold", 10)
        total_taxable = sum(float(inv.taxable_value or 0) for inv in invoices)
        total_tax = sum(float(inv.tax_amount or 0) for inv in invoices)
        total_amount = sum(float(inv.total_amount or 0) for inv in invoices)
        line(
            f"{'TOTAL':<35} "
            f"{fmt(total_taxable):>12} {fmt(total_tax):>12} "
            f"{fmt(total_amount):>12}"
        )

    p.showPage()
    p.save()
    buffer.seek(0)

    filename = f"{client.name.replace(' ', '_')}_invoices_{date.today().isoformat()}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
