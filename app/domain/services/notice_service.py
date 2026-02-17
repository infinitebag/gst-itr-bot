# app/domain/services/notice_service.py
"""
GST Notice management service.

Handles tracking, uploading, and responding to GST notices.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("notice_service")


async def create_notice(
    gstin: str,
    user_id: int,
    notice_type: str,
    description: str,
    due_date: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    """Record a new GST notice.

    Returns
    -------
    dict
        ``{"success": True, "notice_id": int, ...}``
    """
    from app.infrastructure.db.models import GSTNotice
    from datetime import date as date_type

    parsed_date = None
    if due_date:
        try:
            parts = due_date.split("-")
            if len(parts) == 3:
                parsed_date = date_type(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            pass

    notice = GSTNotice(
        gstin=gstin,
        user_id=user_id,
        notice_type=notice_type,
        description=description,
        due_date=parsed_date,
        status="received",
    )
    db.add(notice)
    await db.commit()
    await db.refresh(notice)

    return {
        "success": True,
        "notice_id": notice.id,
        "notice_type": notice_type,
        "status": "received",
    }


async def list_pending_notices(
    gstin: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """List pending/unresolved notices for a GSTIN."""
    from app.infrastructure.db.models import GSTNotice

    stmt = (
        select(GSTNotice)
        .where(
            GSTNotice.gstin == gstin,
            GSTNotice.status.in_(["received", "acknowledged"]),
        )
        .order_by(GSTNotice.due_date.asc().nulls_last())
    )
    result = await db.execute(stmt)
    notices = result.scalars().all()

    return [
        {
            "notice_id": n.id,
            "notice_type": n.notice_type,
            "description": n.description,
            "due_date": str(n.due_date) if n.due_date else None,
            "status": n.status,
        }
        for n in notices
    ]


async def update_notice_status(
    notice_id: int,
    status: str,
    response_text: str | None,
    db: AsyncSession,
) -> bool:
    """Update notice status and optional response text.

    Valid statuses: received → acknowledged → responded → resolved
    """
    from app.infrastructure.db.models import GSTNotice

    stmt = select(GSTNotice).where(GSTNotice.id == notice_id)
    result = await db.execute(stmt)
    notice = result.scalar_one_or_none()
    if not notice:
        return False

    notice.status = status
    if response_text:
        notice.response_text = response_text
    await db.commit()
    return True
