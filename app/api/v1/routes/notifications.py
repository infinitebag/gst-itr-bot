# app/api/v1/routes/notifications.py
"""Proactive notification management API (Phase 10)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok
from app.core.db import get_db
from app.infrastructure.db.models import User

logger = logging.getLogger("api.v1.notifications")

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationPrefsRequest(BaseModel):
    filing_reminders: bool = Field(default=True)
    risk_alerts: bool = Field(default=False)
    status_updates: bool = Field(default=True)


@router.get("/preferences")
async def get_notification_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's notification preferences."""
    from app.domain.services.notification_service import get_user_notification_preferences
    prefs = await get_user_notification_preferences(user.id, db)
    return ok(data=prefs)


@router.put("/preferences")
async def update_notification_preferences(
    body: NotificationPrefsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification preferences."""
    from app.domain.services.notification_service import update_user_notification_preferences
    prefs = body.model_dump()
    await update_user_notification_preferences(user.id, prefs, db)
    return ok(data=prefs, message="Preferences updated")


@router.get("/scheduled")
async def list_scheduled_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List upcoming scheduled notifications for the current user."""
    from sqlalchemy import select
    from app.infrastructure.db.models import NotificationSchedule
    stmt = (
        select(NotificationSchedule)
        .where(
            NotificationSchedule.user_id == user.id,
            NotificationSchedule.status == "pending",
        )
        .order_by(NotificationSchedule.scheduled_for)
        .limit(20)
    )
    result = await db.execute(stmt)
    schedules = result.scalars().all()
    items = [
        {
            "id": s.id,
            "notification_type": s.notification_type,
            "scheduled_for": s.scheduled_for.isoformat() if s.scheduled_for else None,
            "template_name": s.template_name,
            "status": s.status,
        }
        for s in schedules
    ]
    return ok(data=items, message=f"{len(items)} upcoming notification(s)")


@router.post("/schedule-reminders")
async def trigger_reminder_scheduling(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger filing reminder scheduling (admin use)."""
    from app.domain.services.notification_service import schedule_filing_reminders
    count = await schedule_filing_reminders(db)
    return ok(data={"scheduled": count}, message=f"Scheduled {count} reminder(s)")
