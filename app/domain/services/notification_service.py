# app/domain/services/notification_service.py
"""
Proactive notification service.

Schedules and sends filing reminders, risk alerts, and status updates
via WhatsApp template messages.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("notification_service")

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

# GST filing deadlines (day of month)
GST_DEADLINES = {
    "GSTR-3B": 20,   # 20th of next month
    "GSTR-1": 11,    # 11th of next month
}

# Reminder intervals (days before deadline)
REMINDER_INTERVALS = [7, 3, 1]


async def schedule_filing_reminders(db: AsyncSession) -> int:
    """Schedule reminders for upcoming GST deadlines.

    Creates NotificationSchedule entries for:
    - 7 days before: informational reminder
    - 3 days before: warning reminder
    - 1 day before: urgent reminder

    Returns count of newly scheduled notifications.
    """
    from app.infrastructure.db.models import NotificationSchedule, User

    now = datetime.now(IST)
    count = 0

    # Get all active users
    stmt = select(User).where(User.is_active.is_(True))
    result = await db.execute(stmt)
    users = result.scalars().all()

    for user in users:
        for form_type, deadline_day in GST_DEADLINES.items():
            # Calculate next deadline
            if now.day <= deadline_day:
                deadline = now.replace(day=deadline_day, hour=23, minute=59, second=0, microsecond=0)
            else:
                # Next month
                if now.month == 12:
                    deadline = now.replace(year=now.year + 1, month=1, day=deadline_day,
                                           hour=23, minute=59, second=0, microsecond=0)
                else:
                    deadline = now.replace(month=now.month + 1, day=deadline_day,
                                           hour=23, minute=59, second=0, microsecond=0)

            for days_before in REMINDER_INTERVALS:
                send_at = deadline - timedelta(days=days_before)
                if send_at < now:
                    continue  # Already past this reminder window

                # Check if already scheduled
                check_stmt = select(NotificationSchedule).where(
                    NotificationSchedule.user_id == user.id,
                    NotificationSchedule.notification_type == "filing_reminder",
                    NotificationSchedule.scheduled_for == send_at.replace(hour=9, minute=0, second=0),
                )
                check_result = await db.execute(check_stmt)
                if check_result.scalar_one_or_none():
                    continue  # Already scheduled

                # Determine template and urgency
                if days_before == 7:
                    template_name = "filing_reminder_7d"
                elif days_before == 3:
                    template_name = "filing_reminder_3d"
                else:
                    template_name = "filing_reminder_1d"

                period = deadline.strftime("%b %Y")
                notification = NotificationSchedule(
                    user_id=user.id,
                    notification_type="filing_reminder",
                    scheduled_for=send_at.replace(hour=9, minute=0, second=0),
                    status="pending",
                    template_name=template_name,
                    template_params={
                        "form_type": form_type,
                        "period": period,
                        "days_remaining": days_before,
                    },
                )
                db.add(notification)
                count += 1

    await db.commit()
    logger.info("Scheduled %d filing reminders", count)
    return count


async def schedule_risk_alerts(db: AsyncSession) -> int:
    """Schedule risk alert notifications for enterprise users with high-risk scores.

    Returns count of newly scheduled notifications.
    """
    from app.infrastructure.db.models import (
        NotificationSchedule, RiskAssessment, ReturnPeriod, BusinessClient,
    )

    now = datetime.now(IST)
    count = 0

    # Find recent high-risk assessments with their periods
    stmt = (
        select(RiskAssessment, ReturnPeriod.gstin)
        .join(ReturnPeriod, RiskAssessment.period_id == ReturnPeriod.id)
        .where(
            RiskAssessment.risk_score >= 70,
            RiskAssessment.created_at >= now - timedelta(days=1),
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    for assessment, gstin in rows:
        # Find user via business client
        bc_stmt = select(BusinessClient).where(
            BusinessClient.gstin == gstin,
            BusinessClient.segment == "enterprise",
        )
        bc_result = await db.execute(bc_stmt)
        bc = bc_result.scalar_one_or_none()
        if not bc:
            continue

        # Check if already notified
        check_stmt = select(NotificationSchedule).where(
            NotificationSchedule.gstin == gstin,
            NotificationSchedule.notification_type == "risk_alert",
            NotificationSchedule.scheduled_for >= now - timedelta(days=1),
        )
        check_result = await db.execute(check_stmt)
        if check_result.scalar_one_or_none():
            continue

        notification = NotificationSchedule(
            gstin=gstin,
            notification_type="risk_alert",
            scheduled_for=now,
            status="pending",
            template_name="risk_alert",
            template_params={
                "gstin": gstin,
                "score": assessment.risk_score,
                "risk_level": assessment.risk_level,
            },
        )
        db.add(notification)
        count += 1

    await db.commit()
    logger.info("Scheduled %d risk alerts", count)
    return count


async def process_pending_notifications(db: AsyncSession) -> int:
    """Send all pending notifications that are due.

    Returns count of successfully sent notifications.
    """
    from app.infrastructure.db.models import NotificationSchedule, User
    from app.infrastructure.external.whatsapp_client import send_whatsapp_template

    now = datetime.now(IST)
    count = 0

    stmt = select(NotificationSchedule).where(
        NotificationSchedule.status == "pending",
        NotificationSchedule.scheduled_for <= now,
    ).limit(100)
    result = await db.execute(stmt)
    notifications = result.scalars().all()

    for notif in notifications:
        try:
            # Get user's WhatsApp number
            user_stmt = select(User).where(User.id == notif.user_id)
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if not user or not user.whatsapp_number:
                notif.status = "failed"
                continue

            # Determine language
            lang = "en"  # Default, could be stored in user preferences

            # Build template components
            components = []
            if notif.template_params:
                body_params = [
                    {"type": "text", "text": str(v)}
                    for v in notif.template_params.values()
                ]
                components.append({"type": "body", "parameters": body_params})

            await send_whatsapp_template(
                user.whatsapp_number,
                notif.template_name,
                lang,
                components=components if components else None,
            )

            notif.status = "sent"
            notif.sent_at = now
            count += 1

        except Exception:
            logger.exception("Failed to send notification %d", notif.id)
            notif.status = "failed"

    await db.commit()
    logger.info("Sent %d notifications", count)
    return count


async def get_user_notification_preferences(
    user_id: int,
    db: AsyncSession,
) -> dict[str, bool]:
    """Get notification preferences for a user.

    Returns a dict of preference flags.
    Default: all enabled.
    """
    # For now, store in session/user metadata
    # Future: dedicated preferences table
    return {
        "filing_reminders": True,
        "risk_alerts": True,
        "status_updates": True,
    }


async def update_notification_preferences(
    user_id: int,
    prefs: dict[str, bool],
    db: AsyncSession,
) -> None:
    """Update notification preferences for a user."""
    # Future: persist to dedicated preferences table
    logger.info("Updated notification prefs for user %d: %s", user_id, prefs)
