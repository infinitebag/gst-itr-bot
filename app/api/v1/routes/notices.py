# app/api/v1/routes/notices.py
"""GST Notice management API (Phase 9B)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok, error
from app.core.db import get_db
from app.infrastructure.db.models import User

logger = logging.getLogger("api.v1.notices")

router = APIRouter(prefix="/notices", tags=["Notice Management"])


class CreateNoticeRequest(BaseModel):
    gstin: str = Field(..., min_length=15, max_length=15)
    notice_type: str = Field(..., description="ASMT-10, DRC-01, REG-17, etc.")
    description: str = Field(default="")
    due_date: str = Field(default="", description="DD-MM-YYYY format")


class UpdateNoticeRequest(BaseModel):
    status: str = Field(..., description="received | acknowledged | responded | resolved")
    response_text: str = Field(default="")


@router.get("/")
async def list_notices(
    gstin: str = Query(..., min_length=15, max_length=15),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending GST notices for a GSTIN."""
    from app.domain.services.notice_service import list_pending_notices
    notices = await list_pending_notices(gstin, db)
    return ok(data=notices, message=f"Found {len(notices)} notice(s)")


@router.post("/")
async def create_notice(
    body: CreateNoticeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a new GST notice."""
    from app.domain.services.notice_service import create_notice
    result = await create_notice(
        gstin=body.gstin,
        user_id=user.id,
        notice_type=body.notice_type,
        description=body.description,
        due_date=body.due_date,
        db=db,
    )
    if result["success"]:
        return ok(data=result, message="Notice recorded")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error", "Failed"))


@router.put("/{notice_id}")
async def update_notice(
    notice_id: int,
    body: UpdateNoticeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a notice status and response."""
    from app.domain.services.notice_service import update_notice_status
    result = await update_notice_status(notice_id, body.status, body.response_text, db)
    if result["success"]:
        return ok(data=result, message="Notice updated")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("error", "Not found"))
