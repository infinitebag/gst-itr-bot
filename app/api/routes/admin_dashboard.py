# app/api/routes/admin_dashboard.py

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token, verify_admin_form_token
from app.core.config import settings
from app.core.db import get_db
from app.infrastructure.audit import log_admin_action
from app.infrastructure.db.models import WhatsAppDeadLetter, WhatsAppMessageLog

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin/ui", tags=["admin-ui"])


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
            "admin_token": "",  # SECURITY: Never expose ADMIN_API_KEY in HTML; use proper CSRF tokens
        },
    )


@router.post("/dead-letters/{dl_id}/replay")
async def dead_letter_replay_form(
    dl_id: int,
    request: Request,
    admin_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    # Form-based auth: timing-safe compare with ADMIN_API_KEY
    verify_admin_form_token(admin_token, request)
    log_admin_action("dead_letter_replay", admin_ip=request.client.host if request.client else "", details={"dl_id": dl_id})

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
                case((WhatsAppMessageLog.status == "sent", 1), else_=0)
            ).label("sent_count"),
            func.sum(
                case(
                    (WhatsAppMessageLog.status == "dropped_rate_limit", 1), else_=0
                )
            ).label("dropped_count"),
            func.max(WhatsAppMessageLog.created_at).label("last_at"),
        )
        .where(WhatsAppMessageLog.created_at >= since)
        .group_by(WhatsAppMessageLog.to_number)
        .order_by(
            func.sum(
                case((WhatsAppMessageLog.status == "sent", 1), else_=0)
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
