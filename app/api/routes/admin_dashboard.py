# app/api/routes/admin_dashboard.py

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.infrastructure.db.models import WhatsAppDeadLetter, WhatsAppMessageLog

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin/ui", tags=["admin-ui"])


async def require_admin_token(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not configured")
    if x_admin_token != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.get("/dead-letters")
async def dead_letters_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    stmt = (
        select(WhatsAppDeadLetter)
        .order_by(WhatsAppDeadLetter.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    rows: list[WhatsAppDeadLetter] = list(result.scalars().all())

    items: list[dict[str, Any]] = []
    for dl in rows:
        items.append(
            {
                "id": dl.id,
                "to_number": dl.to_number,
                "text": dl.text,
                "failure_reason": dl.failure_reason,
                "retry_count": dl.retry_count,
                "created_at": dl.created_at.isoformat() if dl.created_at else None,
            }
        )

    return templates.TemplateResponse(
        "admin/dead_letters.html",
        {
            "request": request,
            "title": "WhatsApp Dead Letters",
            "items": items,
            "count": len(items),
            "admin_token": settings.ADMIN_API_KEY,  # used in form hidden field
        },
    )


@router.post("/dead-letters/{dl_id}/replay")
async def dead_letter_replay_form(
    dl_id: int,
    request: Request,
    admin_token: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Form-based auth: compare with ADMIN_API_KEY
    if admin_token != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin token in form")

    # We reuse the JSON admin endpoint logic:
    from app.api.routes.admin_whatsapp import replay_dead_letter  # avoid duplication

    await replay_dead_letter(dl_id=dl_id, db=db)

    # Redirect back to dead-letter list
    return RedirectResponse(url="/admin/ui/dead-letters", status_code=303)


@router.get("/usage")
async def usage_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
    days: int = Query(7, ge=1, le=90),
):
    """
    Simple usage stats page based on WhatsAppMessageLog + DeadLetter.
    Shows:
      - total sent
      - total dropped
      - per-user breakdown
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # Total sent
    sent_stmt = select(func.count(WhatsAppMessageLog.id)).where(
        WhatsAppMessageLog.status == "sent",
        WhatsAppMessageLog.created_at >= since,
    )
    sent_count = (await db.execute(sent_stmt)).scalar_one() or 0

    # Total dropped by rate limit
    dropped_stmt = select(func.count(WhatsAppMessageLog.id)).where(
        WhatsAppMessageLog.status == "dropped_rate_limit",
        WhatsAppMessageLog.created_at >= since,
    )
    dropped_count = (await db.execute(dropped_stmt)).scalar_one() or 0

    # Per-user breakdown (top 50)
    per_user_stmt = (
        select(
            WhatsAppMessageLog.to_number,
            func.sum(
                func.case((WhatsAppMessageLog.status == "sent", 1), else_=0)
            ).label("sent_count"),
            func.sum(
                func.case(
                    (WhatsAppMessageLog.status == "dropped_rate_limit", 1), else_=0
                )
            ).label("dropped_count"),
            func.max(WhatsAppMessageLog.created_at).label("last_at"),
        )
        .where(WhatsAppMessageLog.created_at >= since)
        .group_by(WhatsAppMessageLog.to_number)
        .order_by(
            func.sum(
                func.case((WhatsAppMessageLog.status == "sent", 1), else_=0)
            ).desc()
        )
        .limit(50)
    )

    result = await db.execute(per_user_stmt)
    rows = result.all()

    users: list[dict[str, Any]] = []
    for to_number, sent, dropped, last_at in rows:
        users.append(
            {
                "to_number": to_number,
                "sent_count": int(sent or 0),
                "dropped_count": int(dropped or 0),
                "last_at": last_at.isoformat() if last_at else None,
            }
        )

    return templates.TemplateResponse(
        "admin/usage.html",
        {
            "request": request,
            "title": "WhatsApp Usage Stats",
            "days": days,
            "total_sent": sent_count,
            "total_dropped": dropped_count,
            "users": users,
        },
    )
