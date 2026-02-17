# app/api/v1/routes/user_gstins.py
"""Multi-GSTIN management API (Phase 8)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok, error, paginated
from app.core.db import get_db
from app.infrastructure.db.models import User

logger = logging.getLogger("api.v1.user_gstins")

router = APIRouter(prefix="/user-gstins", tags=["Multi-GSTIN"])


class AddGSTINRequest(BaseModel):
    gstin: str = Field(..., min_length=15, max_length=15, description="15-character GSTIN")
    label: str = Field(default="", max_length=100, description="Friendly label (e.g. 'Mumbai Branch')")


class SetPrimaryRequest(BaseModel):
    gstin: str = Field(..., min_length=15, max_length=15)


@router.get("/")
async def list_user_gstins(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all GSTINs registered for the current user."""
    from app.domain.services.multi_gstin_service import list_gstins
    gstins = await list_gstins(user.id, db)
    return ok(data=gstins, message=f"Found {len(gstins)} GSTIN(s)")


@router.post("/")
async def add_user_gstin(
    body: AddGSTINRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new GSTIN for the current user."""
    from app.domain.services.multi_gstin_service import add_gstin
    result = await add_gstin(user.id, body.gstin, body.label, db)
    if result["success"]:
        return ok(data=result, message=f"GSTIN {body.gstin} added")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error", "Failed to add GSTIN"))


@router.delete("/{gstin}")
async def remove_user_gstin(
    gstin: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a GSTIN from the current user."""
    from app.domain.services.multi_gstin_service import remove_gstin
    result = await remove_gstin(user.id, gstin, db)
    if result:
        return ok(message=f"GSTIN {gstin} removed")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GSTIN not found")


@router.put("/primary")
async def set_primary_gstin(
    body: SetPrimaryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a GSTIN as the primary for the current user."""
    from app.domain.services.multi_gstin_service import set_primary
    await set_primary(user.id, body.gstin, db)
    return ok(message=f"GSTIN {body.gstin} set as primary")


@router.get("/summary")
async def get_consolidated_summary(
    period: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a consolidated summary across all GSTINs for a period."""
    from app.domain.services.multi_gstin_service import get_consolidated_summary
    from app.domain.services.gst_service import get_current_gst_period
    if not period:
        period = get_current_gst_period()
    summary = await get_consolidated_summary(user.id, period, db)
    return ok(data=summary)
