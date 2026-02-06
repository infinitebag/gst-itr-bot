from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_whatsapp(self, whatsapp_number: str) -> User | None:
        stmt = select(User).where(User.whatsapp_number == whatsapp_number)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_by_whatsapp(self, whatsapp_number: str) -> User:
        user = await self.get_by_whatsapp(whatsapp_number)
        if user:
            return user

        new_user = User(whatsapp_number=whatsapp_number)
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)
        return new_user
