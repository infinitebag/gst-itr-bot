# app/api/routes/admin_whatsapp.py

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token
from app.core.db import get_db
from app.infrastructure.db.models import WhatsAppDeadLetter
from app.infrastructure.external.whatsapp_client import send_whatsapp_text

router = APIRouter(prefix="/admin/whatsapp", tags=["admin-whatsapp"])


# --------- ENDPOINTS ---------


@router.get("/dead-letters", dependencies=[Depends(require_admin_token)])
async def list_dead_letters(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List WhatsApp dead-letter messages (paginated).
    """

    stmt = (
        select(WhatsAppDeadLetter)
        .order_by(WhatsAppDeadLetter.created_at.desc())
        .offset(offset)
        .limit(limit)
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
                "last_error": dl.last_error,
                "retry_count": dl.retry_count,
                "created_at": dl.created_at.isoformat() if dl.created_at else None,
            }
        )

    return {
        "count": len(items),
        "items": items,
        "offset": offset,
        "limit": limit,
    }


@router.get("/dead-letters/{dl_id}", dependencies=[Depends(require_admin_token)])
async def get_dead_letter(
    dl_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get details for a single dead-letter message.
    """
    stmt = select(WhatsAppDeadLetter).where(WhatsAppDeadLetter.id == dl_id)
    result = await db.execute(stmt)
    dl: WhatsAppDeadLetter | None = result.scalar_one_or_none()

    if dl is None:
        raise HTTPException(status_code=404, detail="Dead-letter not found")

    return {
        "id": dl.id,
        "to_number": dl.to_number,
        "text": dl.text,
        "failure_reason": dl.failure_reason,
        "last_error": dl.last_error,
        "retry_count": dl.retry_count,
        "created_at": dl.created_at.isoformat() if dl.created_at else None,
    }


@router.post("/dead-letters/{dl_id}/replay", dependencies=[Depends(require_admin_token)])
async def replay_dead_letter(
    dl_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Replay (re-queue) a dead-letter message to WhatsApp.

    For safety, we do NOT delete the dead-letter row here – you can
    decide later whether to clean it up or keep full history.
    """
    stmt = select(WhatsAppDeadLetter).where(WhatsAppDeadLetter.id == dl_id)
    result = await db.execute(stmt)
    dl: WhatsAppDeadLetter | None = result.scalar_one_or_none()

    if dl is None:
        raise HTTPException(status_code=404, detail="Dead-letter not found")

    # Re-enqueue the message – it will again go through per-user
    # rate limits, global rate limit, and retries.
    await send_whatsapp_text(dl.to_number, dl.text)

    return {
        "status": "replayed",
        "id": dl.id,
        "to_number": dl.to_number,
        "failure_reason": dl.failure_reason,
        "info": "Message has been enqueued again via the normal WhatsApp queue.",
    }
