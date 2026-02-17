# app/api/v1/routes/audit.py
"""Admin audit console REST API."""

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_admin_token

router = APIRouter(prefix="/audit", tags=["Audit Console"])


@router.get("/recent", dependencies=[Depends(require_admin_token)])
async def get_recent_audit(
    limit: int = Query(50, ge=1, le=500),
    actor_type: str | None = Query(None),
    client_gstin: str | None = Query(None),
    action: str | None = Query(None),
):
    """Get recent audit entries with optional filters."""
    from app.domain.services.audit_service import get_recent_audit_entries

    entries = get_recent_audit_entries(
        limit=limit,
        actor_type=actor_type,
        client_gstin=client_gstin,
        action=action,
    )
    return {"ok": True, "entries": entries, "count": len(entries)}


@router.get("/client/{gstin}", dependencies=[Depends(require_admin_token)])
async def get_client_access_summary(gstin: str):
    """Get access summary for a specific client GSTIN."""
    from app.domain.services.audit_service import get_access_summary

    summary = get_access_summary(gstin)
    return {"ok": True, "data": summary}
