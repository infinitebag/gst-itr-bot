from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Session


class SessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user(self, user_id) -> Session | None:
        """
        Return the *most recent* active session for this user, or None.

        We ORDER BY created_at (or updated_at) DESC and LIMIT 1 so that
        even if multiple rows exist, we never raise MultipleResultsFound.
        """
        stmt = (
            select(Session)
            .where(Session.user_id == user_id, Session.active.is_(True))
            .order_by(Session.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: UUID) -> Session:
        session = await self.get_by_user(user_id)
        if session:
            return session

        new_session = Session(
            user_id=user_id,
            language="en",
            step="LANG_SELECT",
            active=True,
        )
        self.db.add(new_session)
        try:
            await self.db.commit()
        except Exception:
            # Handle race condition: another request created the session concurrently
            await self.db.rollback()
            session = await self.get_by_user(user_id)
            if session:
                return session
            raise  # Re-raise if it's a different error
        await self.db.refresh(new_session)
        return new_session

    async def update(self, session: Session, **kwargs) -> Session:
        for k, v in kwargs.items():
            setattr(session, k, v)

        # updated_at will be maintained by DB onupdate trigger
        session.updated_at = datetime.now(timezone.utc)
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def deactivate_all_for_user(self, user_id: UUID) -> None:
        stmt = select(Session).where(Session.user_id == user_id)
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        changed = False
        for s in sessions:
            if s.active:
                s.active = False
                changed = True
                self.db.add(s)
        if changed:
            await self.db.commit()
