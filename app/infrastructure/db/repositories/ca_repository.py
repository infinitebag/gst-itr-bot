
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import BusinessClient, CAUser


class CAUserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, ca_id: int) -> CAUser | None:
        stmt = select(CAUser).where(CAUser.id == ca_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> CAUser | None:
        stmt = select(CAUser).where(CAUser.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[CAUser]:
        stmt = select(CAUser).order_by(CAUser.id.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class BusinessClientRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, client_id: int) -> BusinessClient | None:
        stmt = select(BusinessClient).where(BusinessClient.id == client_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_whatsapp(self, whatsapp_number: str) -> BusinessClient | None:
        stmt = select(BusinessClient).where(
            BusinessClient.whatsapp_number == whatsapp_number
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_ca(self, ca_id: int) -> list[BusinessClient]:
        stmt = select(BusinessClient).where(BusinessClient.ca_id == ca_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[BusinessClient]:
        stmt = select(BusinessClient).order_by(BusinessClient.id.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
