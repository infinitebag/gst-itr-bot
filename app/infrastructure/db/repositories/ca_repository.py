# app/infrastructure/db/repositories/ca_repository.py
"""
Data-access layer for CA users and their business clients.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import BusinessClient, CAUser


# ---------------------------------------------------------------------------
# CA User Repository
# ---------------------------------------------------------------------------

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

    async def create(
        self,
        email: str,
        password_hash: str,
        name: str,
        phone: str | None = None,
        membership_number: str | None = None,
    ) -> CAUser:
        ca = CAUser(
            email=email,
            password_hash=password_hash,
            name=name,
            phone=phone,
            membership_number=membership_number,
        )
        self.db.add(ca)
        await self.db.commit()
        await self.db.refresh(ca)
        return ca

    async def update_last_login(self, ca_id: int) -> None:
        stmt = (
            update(CAUser)
            .where(CAUser.id == ca_id)
            .values(last_login=datetime.now(timezone.utc))
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def update(self, ca_id: int, **kwargs) -> CAUser | None:
        ca = await self.get_by_id(ca_id)
        if ca is None:
            return None
        for key, value in kwargs.items():
            if hasattr(ca, key):
                setattr(ca, key, value)
        await self.db.commit()
        await self.db.refresh(ca)
        return ca

    async def list_pending_approval(self) -> list[CAUser]:
        """Return CA users that are active but not yet approved."""
        stmt = (
            select(CAUser)
            .where(CAUser.approved == False)  # noqa: E712
            .where(CAUser.active == True)  # noqa: E712
            .order_by(CAUser.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def approve(self, ca_id: int) -> CAUser | None:
        """Mark a CA user as approved."""
        return await self.update(
            ca_id,
            approved=True,
            approved_at=datetime.now(timezone.utc),
        )

    async def reject(self, ca_id: int) -> CAUser | None:
        """Reject a CA user by deactivating their account."""
        return await self.update(ca_id, active=False)


# ---------------------------------------------------------------------------
# Business Client Repository
# ---------------------------------------------------------------------------

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
        stmt = (
            select(BusinessClient)
            .where(BusinessClient.ca_id == ca_id)
            .order_by(BusinessClient.name.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[BusinessClient]:
        stmt = select(BusinessClient).order_by(BusinessClient.id.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        ca_id: int,
        name: str,
        gstin: str | None = None,
        whatsapp_number: str | None = None,
        pan: str | None = None,
        email: str | None = None,
        business_type: str | None = None,
        address: str | None = None,
        state_code: str | None = None,
        notes: str | None = None,
    ) -> BusinessClient:
        client = BusinessClient(
            ca_id=ca_id,
            name=name,
            gstin=gstin,
            whatsapp_number=whatsapp_number,
            pan=pan,
            email=email,
            business_type=business_type,
            address=address,
            state_code=state_code,
            notes=notes,
            status="active",
        )
        self.db.add(client)
        await self.db.commit()
        await self.db.refresh(client)
        return client

    async def update(self, client_id: int, **kwargs) -> BusinessClient | None:
        client = await self.get_by_id(client_id)
        if client is None:
            return None
        for key, value in kwargs.items():
            if hasattr(client, key):
                setattr(client, key, value)
        await self.db.commit()
        await self.db.refresh(client)
        return client

    async def deactivate(self, client_id: int) -> None:
        stmt = (
            update(BusinessClient)
            .where(BusinessClient.id == client_id)
            .values(status="inactive")
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def count_for_ca(self, ca_id: int) -> int:
        stmt = (
            select(func.count(BusinessClient.id))
            .where(BusinessClient.ca_id == ca_id)
            .where(BusinessClient.status == "active")
        )
        result = await self.db.execute(stmt)
        return result.scalar_one() or 0

    async def search(self, ca_id: int, query: str) -> list[BusinessClient]:
        """Search clients by name, GSTIN, or WhatsApp number."""
        pattern = f"%{query}%"
        stmt = (
            select(BusinessClient)
            .where(BusinessClient.ca_id == ca_id)
            .where(
                or_(
                    BusinessClient.name.ilike(pattern),
                    BusinessClient.gstin.ilike(pattern),
                    BusinessClient.whatsapp_number.ilike(pattern),
                    BusinessClient.pan.ilike(pattern),
                )
            )
            .order_by(BusinessClient.name.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def transfer_client(
        self, client_id: int, new_ca_id: int
    ) -> BusinessClient | None:
        """Transfer a business client to a different CA user.

        The target CA must exist and be both active and approved.
        Returns the updated BusinessClient, or None if the client or
        a valid target CA was not found.
        """
        # Validate the target CA exists and is active + approved
        target_ca_stmt = (
            select(CAUser)
            .where(CAUser.id == new_ca_id)
            .where(CAUser.active == True)   # noqa: E712
            .where(CAUser.approved == True)  # noqa: E712
        )
        target_result = await self.db.execute(target_ca_stmt)
        if target_result.scalar_one_or_none() is None:
            return None

        return await self.update(client_id, ca_id=new_ca_id)
