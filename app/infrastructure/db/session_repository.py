
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.cache.session_cache import (
    cache_session,
    get_cached_session,
    invalidate_session_cache,
)
from app.infrastructure.db.models import Session


class SessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user(self, user_id: int) -> Session | None:
        """
        Try Redis cache first, then DB.
        """
        cached = await get_cached_session(user_id)
        if cached:
            # Convert dict → Session model (in-memory only)
            return Session(**cached)

        stmt = select(Session).where(Session.user_id == user_id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if session:
            await cache_session(user_id, session.to_dict())

        return session

    async def get_or_create(self, user_id: int) -> Session:
        """
        Return session or create a new one.
        """
        session = await self.get_by_user(user_id)
        if session:
            return session

        new_session = Session(
            user_id=user_id,
            language="en",
        )
        self.db.add(new_session)
        await self.db.commit()
        await self.db.refresh(new_session)

        await cache_session(user_id, new_session.to_dict())
        return new_session

    async def update(self, session: Session, **kwargs) -> Session:
        """
        Update fields and write both DB + Redis.
        """
        for k, v in kwargs.items():
            setattr(session, k, v)

        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        await cache_session(session.user_id, session.to_dict())

        return session

    async def reset(self, user_id: int) -> None:
        """
        Hard reset session.
        """
        stmt = select(Session).where(Session.user_id == user_id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if session:
            await self.db.delete(session)
            await self.db.commit()

        await invalidate_session_cache(user_id)
