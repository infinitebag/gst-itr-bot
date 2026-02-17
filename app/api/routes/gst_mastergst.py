# app/api/routes/gst_mastergst.py
"""
REST API routes for filing GSTR-3B and GSTR-1 via MasterGST sandbox.

These endpoints are designed for mobile/web app integration as well
as the WhatsApp bot backend.
"""

from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.domain.services.gst_export import make_gstr1_json, make_gstr3b_json
from app.domain.services.gst_service import prepare_gstr3b
from app.domain.services.gstr1_service import prepare_gstr1_payload
from app.infrastructure.db.repositories import InvoiceRepository, FilingRepository
from app.infrastructure.external.mastergst_client import MasterGSTClient, MasterGSTError

logger = logging.getLogger("gst_mastergst")
router = APIRouter()

# GSTIN regex: 2-digit state code, 5 alpha, 4 digits, 1 alpha, 1 alphanumeric, Z, 1 alphanumeric
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Period regex: YYYY-MM
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ============================================================
# Pydantic response models — for OpenAPI docs + client SDKs
# ============================================================

class FilingDebugInfo(BaseModel):
    user_id: str
    period: str
    gstin: str
    invoice_count: int = 0
    b2b_parties: int = 0
    b2b_invoices: int = 0
    b2c_invoices: int = 0


class GstFilingResponse(BaseModel):
    """Response from a GST filing operation."""
    status: str = Field(description="Filing status: submitted, error")
    reference_number: str = Field(default="", description="MasterGST acknowledgement/reference")
    form_type: str = Field(description="GSTR-3B or GSTR-1")
    period: str = Field(description="Filing period YYYY-MM")
    gstin: str = Field(description="GSTIN used for filing")
    debug: FilingDebugInfo
    save_response: dict = Field(default_factory=dict, description="MasterGST save API response")
    submit_response: dict = Field(default_factory=dict, description="MasterGST submit API response")


class FilingHistoryItem(BaseModel):
    """A single filing history record."""
    id: str
    filing_type: str
    form_type: str
    period: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    status: str
    reference_number: Optional[str] = None
    filed_at: Optional[str] = None
    created_at: str


class FilingHistoryResponse(BaseModel):
    """Response for filing history query."""
    user_id: str
    total: int
    records: list[FilingHistoryItem]


# ============================================================
# Helpers
# ============================================================

def _validate_period(period: str) -> date:
    """Parse and validate a YYYY-MM period string."""
    if not _PERIOD_RE.match(period):
        raise HTTPException(
            status_code=400,
            detail="Invalid period format. Use YYYY-MM (e.g. 2025-11). Month must be 01-12.",
        )
    year, month = int(period[:4]), int(period[5:7])
    return date(year, month, 1)


def _validate_gstin(gstin: str | None) -> str:
    """Validate and return GSTIN, falling back to sandbox config."""
    use_gstin = gstin or getattr(settings, "GSTIN", None)
    if not use_gstin:
        raise HTTPException(
            status_code=400,
            detail="GSTIN is required. Pass it as a parameter or set GSTIN in config.",
        )
    if not _GSTIN_RE.match(use_gstin):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid GSTIN format: {use_gstin}. Expected 15-character format like 27ABCDE1234F1Z5.",
        )
    return use_gstin


def _check_mastergst_credentials() -> None:
    """Validate that required MasterGST credentials are configured."""
    missing = []
    if not settings.MASTERGST_CLIENT_ID:
        missing.append("MASTERGST_CLIENT_ID")
    if not settings.MASTERGST_CLIENT_SECRET:
        missing.append("MASTERGST_CLIENT_SECRET")
    if not settings.MASTERGST_EMAIL:
        missing.append("MASTERGST_EMAIL")
    if not settings.MASTERGST_GST_USERNAME:
        missing.append("MASTERGST_GST_USERNAME")
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"MasterGST credentials not configured: {', '.join(missing)}",
        )


# ============================================================
# GST Filing Endpoints
# ============================================================

@router.post("/gstr3b/file", response_model=GstFilingResponse)
async def file_gstr3b_to_mastergst(
    user_id: str = Query(..., description="Internal user ID whose invoices to use"),
    period: str = Query(..., description="Return period YYYY-MM, e.g. 2025-11"),
    gstin: str | None = Query(None, description="GSTIN; defaults to GSTIN"),
    db: AsyncSession = Depends(get_db),
) -> GstFilingResponse:
    """
    Build GSTR-3B JSON from saved invoices, then submit to MasterGST sandbox.

    Flow: DB invoices → GSTR-3B summary → MasterGST save → submit → filing record.
    """
    _check_mastergst_credentials()

    period_start = _validate_period(period)
    last_day = monthrange(period_start.year, period_start.month)[1]
    period_end = date(period_start.year, period_start.month, last_day)

    use_gstin = _validate_gstin(gstin)

    # Get invoices from DB
    repo = InvoiceRepository(db)
    invoices_db = await repo.list_for_period(
        user_id=user_id,
        start=period_start,
        end=period_end,
    )

    if not invoices_db:
        raise HTTPException(status_code=400, detail="No invoices found for that period")

    # Convert DB Invoice objects to dicts for prepare_gstr3b
    invoice_dicts = [
        {
            "taxable_value": inv.taxable_value,
            "igst_amount": inv.igst_amount,
            "cgst_amount": inv.cgst_amount,
            "sgst_amount": inv.sgst_amount,
            "cess_amount": 0,
            "reverse_charge": False,
            "itc_eligible": True,
        }
        for inv in invoices_db
    ]

    summary = prepare_gstr3b(invoice_dicts)
    gstr3b_json = make_gstr3b_json(use_gstin, period_start, summary)

    # Authenticate + Save + Submit via MasterGST
    client = MasterGSTClient()
    try:
        auth_token = await client.authenticate(use_gstin)

        save_resp = await client.save_gstr3b(
            gstin=use_gstin,
            fp=gstr3b_json["fp"],
            payload=gstr3b_json,
            auth_token=auth_token,
        )

        submit_resp = await client.submit_gstr3b(
            gstin=use_gstin,
            fp=gstr3b_json["fp"],
            auth_token=auth_token,
        )

        # Save filing record to DB
        filing_repo = FilingRepository(db)
        ref_number = submit_resp.get("reference_id") or submit_resp.get("ack_num", "")
        await filing_repo.create_record(
            user_id=user_id,
            filing_type="GST",
            form_type="GSTR-3B",
            period=period,
            gstin=use_gstin,
            status="submitted",
            reference_number=ref_number,
            payload=gstr3b_json,
            response=submit_resp,
        )

    except MasterGSTError as e:
        logger.error("MasterGST GSTR-3B filing failed [%d]: %s", e.status_code, e)
        detail = e.response.get("message", str(e)) if e.response else str(e)
        raise HTTPException(status_code=502, detail=detail)

    return GstFilingResponse(
        status="submitted",
        reference_number=ref_number,
        form_type="GSTR-3B",
        period=period,
        gstin=use_gstin,
        debug=FilingDebugInfo(
            user_id=user_id,
            period=period,
            gstin=use_gstin,
            invoice_count=len(invoices_db),
        ),
        save_response=save_resp,
        submit_response=submit_resp,
    )


@router.post("/gstr1/file", response_model=GstFilingResponse)
async def file_gstr1_to_mastergst(
    user_id: str = Query(..., description="Internal user ID whose invoices to use"),
    period: str = Query(..., description="Return period YYYY-MM, e.g. 2025-11"),
    gstin: str | None = Query(None, description="GSTIN; defaults to GSTIN"),
    db: AsyncSession = Depends(get_db),
) -> GstFilingResponse:
    """
    Build GSTR-1 JSON from saved invoices, then submit to MasterGST sandbox.

    Flow: DB invoices → GSTR-1 payload → MasterGST save → submit → filing record.
    """
    _check_mastergst_credentials()

    period_start = _validate_period(period)
    last_day = monthrange(period_start.year, period_start.month)[1]
    period_end = date(period_start.year, period_start.month, last_day)

    use_gstin = _validate_gstin(gstin)

    repo = InvoiceRepository(db)
    payload_obj = await prepare_gstr1_payload(
        user_id=user_id,
        gstin=use_gstin,
        period_start=period_start,
        period_end=period_end,
        repo=repo,
    )

    if not payload_obj.b2b and not payload_obj.b2c:
        raise HTTPException(status_code=400, detail="No invoices found for that period")

    gstr1_json = make_gstr1_json(payload_obj)

    # Authenticate + Save + Submit via MasterGST
    client = MasterGSTClient()
    try:
        auth_token = await client.authenticate(use_gstin)

        save_resp = await client.save_gstr1(
            gstin=use_gstin,
            fp=gstr1_json["fp"],
            payload=gstr1_json,
            auth_token=auth_token,
        )

        submit_resp = await client.submit_gstr1(
            gstin=use_gstin,
            fp=gstr1_json["fp"],
            auth_token=auth_token,
        )

        # Save filing record to DB
        filing_repo = FilingRepository(db)
        ref_number = submit_resp.get("reference_id") or submit_resp.get("ack_num", "")
        b2b_invoices = sum(len(entry.inv) for entry in payload_obj.b2b)

        await filing_repo.create_record(
            user_id=user_id,
            filing_type="GST",
            form_type="GSTR-1",
            period=period,
            gstin=use_gstin,
            status="submitted",
            reference_number=ref_number,
            payload=gstr1_json,
            response=submit_resp,
        )

    except MasterGSTError as e:
        logger.error("MasterGST GSTR-1 filing failed [%d]: %s", e.status_code, e)
        detail = e.response.get("message", str(e)) if e.response else str(e)
        raise HTTPException(status_code=502, detail=detail)

    return GstFilingResponse(
        status="submitted",
        reference_number=ref_number,
        form_type="GSTR-1",
        period=period,
        gstin=use_gstin,
        debug=FilingDebugInfo(
            user_id=user_id,
            period=period,
            gstin=use_gstin,
            b2b_parties=len(payload_obj.b2b),
            b2b_invoices=b2b_invoices,
            b2c_invoices=len(payload_obj.b2c),
        ),
        save_response=save_resp,
        submit_response=submit_resp,
    )


# ============================================================
# Filing History Endpoint
# ============================================================

@router.get("/filings", response_model=FilingHistoryResponse)
async def get_filing_history(
    user_id: str = Query(..., description="User ID to fetch filing history for"),
    filing_type: str | None = Query(None, description="Filter: GST or ITR"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
) -> FilingHistoryResponse:
    """
    Fetch filing history for a user.

    Returns all GST and ITR filing records, newest first.
    Use `filing_type=GST` or `filing_type=ITR` to filter.
    """
    filing_repo = FilingRepository(db)
    records = await filing_repo.get_by_user(user_id, limit=limit)

    # Filter by type if specified
    if filing_type:
        records = [r for r in records if r.filing_type == filing_type.upper()]

    items = [
        FilingHistoryItem(
            id=str(r.id),
            filing_type=r.filing_type,
            form_type=r.form_type,
            period=r.period,
            gstin=r.gstin,
            pan=r.pan,
            status=r.status,
            reference_number=r.reference_number,
            filed_at=r.filed_at.isoformat() if r.filed_at else None,
            created_at=r.created_at.isoformat(),
        )
        for r in records
    ]

    return FilingHistoryResponse(
        user_id=user_id,
        total=len(items),
        records=items,
    )
