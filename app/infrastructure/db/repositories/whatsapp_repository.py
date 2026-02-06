from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import WhatsAppDeadLetter, WhatsAppMessageLog


class WhatsAppDeadLetterRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_recent(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WhatsAppDeadLetter]:
        stmt = (
            select(WhatsAppDeadLetter)
            .order_by(WhatsAppDeadLetter.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, dl_id: int) -> WhatsAppDeadLetter | None:
        stmt = select(WhatsAppDeadLetter).where(WhatsAppDeadLetter.id == dl_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


class WhatsAppMessageLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def count_sent_since(self, since: datetime) -> int:
        stmt = select(func.count(WhatsAppMessageLog.id)).where(
            WhatsAppMessageLog.status == "sent",
            WhatsAppMessageLog.created_at >= since,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one() or 0

    async def count_dropped_since(self, since: datetime) -> int:
        stmt = select(func.count(WhatsAppMessageLog.id)).where(
            WhatsAppMessageLog.status == "dropped_rate_limit",
            WhatsAppMessageLog.created_at >= since,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one() or 0

    async def per_user_stats(
        self,
        since: datetime,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                WhatsAppMessageLog.to_number,
                func.sum(
                    func.case(
                        (WhatsAppMessageLog.status == "sent", 1),
                        else_=0,
                    )
                ).label("sent_count"),
                func.sum(
                    func.case(
                        (WhatsAppMessageLog.status == "dropped_rate_limit", 1),
                        else_=0,
                    )
                ).label("dropped_count"),
                func.max(WhatsAppMessageLog.created_at).label("last_at"),
            )
            .where(WhatsAppMessageLog.created_at >= since)
            .group_by(WhatsAppMessageLog.to_number)
            .order_by(
                func.sum(
                    func.case(
                        (WhatsAppMessageLog.status == "sent", 1),
                        else_=0,
                    )
                ).desc()
            )
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        out: list[dict[str, Any]] = []
        for to_number, sent, dropped, last_at in rows:
            out.append(
                {
                    "to_number": to_number,
                    "sent_count": int(sent or 0),
                    "dropped_count": int(dropped or 0),
                    "last_at": last_at,
                }
            )
        return out
