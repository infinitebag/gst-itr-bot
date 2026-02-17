# app/infrastructure/db/repositories/filing_repository.py

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import FilingRecord, BusinessClient


class FilingRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_record(
        self,
        user_id: uuid.UUID,
        filing_type: str,
        form_type: str,
        period: str,
        *,
        gstin: str | None = None,
        pan: str | None = None,
        status: str = "draft",
        reference_number: str | None = None,
        payload: dict | None = None,
        response: dict | None = None,
        ca_id: int | None = None,
    ) -> FilingRecord:
        """Create a new filing record."""
        record = FilingRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            filing_type=filing_type,
            form_type=form_type,
            period=period,
            gstin=gstin,
            pan=pan,
            status=status,
            reference_number=reference_number,
            payload_json=json.dumps(payload, default=str) if payload else None,
            response_json=json.dumps(response, default=str) if response else None,
            filed_at=datetime.now(timezone.utc) if status in ("submitted", "acknowledged") else None,
            ca_id=ca_id,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_by_id(
        self, record_id: uuid.UUID
    ) -> FilingRecord | None:
        """Fetch a single filing record by ID."""
        stmt = select(FilingRecord).where(FilingRecord.id == record_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        record_id: uuid.UUID,
        status: str,
        *,
        reference_number: str | None = None,
        response: dict | None = None,
    ) -> FilingRecord | None:
        """Update the status of a filing record after API response."""
        stmt = select(FilingRecord).where(FilingRecord.id == record_id)
        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None

        record.status = status
        if reference_number:
            record.reference_number = reference_number
        if response:
            record.response_json = json.dumps(response, default=str)
        if status in ("submitted", "acknowledged"):
            record.filed_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def update_ca_review(
        self,
        record_id: uuid.UUID,
        status: str,
        *,
        ca_notes: str | None = None,
        ca_reviewed_at: datetime | None = None,
        reference_number: str | None = None,
        response: dict | None = None,
        filed_at: datetime | None = None,
    ) -> FilingRecord | None:
        """Update filing status and CA review fields."""
        record = await self.get_by_id(record_id)
        if not record:
            return None

        record.status = status
        if ca_notes is not None:
            record.ca_notes = ca_notes
        if ca_reviewed_at is not None:
            record.ca_reviewed_at = ca_reviewed_at
        if reference_number is not None:
            record.reference_number = reference_number
        if response is not None:
            record.response_json = json.dumps(response, default=str)
        if filed_at is not None:
            record.filed_at = filed_at

        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
    ) -> list[FilingRecord]:
        """List filing history for a user, most recent first."""
        stmt = (
            select(FilingRecord)
            .where(FilingRecord.user_id == user_id)
            .order_by(FilingRecord.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_period(
        self,
        user_id: uuid.UUID,
        form_type: str,
        period: str,
    ) -> FilingRecord | None:
        """Check if a user has already filed for a given form_type + period."""
        stmt = (
            select(FilingRecord)
            .where(
                and_(
                    FilingRecord.user_id == user_id,
                    FilingRecord.form_type == form_type,
                    FilingRecord.period == period,
                    FilingRecord.status.in_(["submitted", "acknowledged"]),
                )
            )
            .order_by(FilingRecord.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_ca(
        self,
        ca_id: int,
        filing_type: str = "GST",
        status: str | None = None,
    ) -> list[FilingRecord]:
        """List all filings for a CA's clients (any status or filtered)."""
        stmt = select(FilingRecord).where(
            FilingRecord.ca_id == ca_id,
            FilingRecord.filing_type == filing_type,
        )
        if status:
            stmt = stmt.where(FilingRecord.status == status)
        stmt = stmt.order_by(FilingRecord.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_unassigned_filings(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[FilingRecord], int]:
        """
        Return GST filings where ca_id IS NULL and status is 'pending_ca_review'.
        Returns (records, total_count).
        """
        base = select(FilingRecord).where(
            FilingRecord.ca_id.is_(None),
            FilingRecord.status == "pending_ca_review",
        )
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one() or 0

        stmt = base.order_by(FilingRecord.created_at.asc()).offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def assign_ca(
        self,
        filing_id: uuid.UUID,
        ca_id: int,
    ) -> FilingRecord | None:
        """Assign a CA to an unassigned filing record."""
        record = await self.get_by_id(filing_id)
        if not record:
            return None
        record.ca_id = ca_id
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_changes_requested(
        self,
        user_id: uuid.UUID,
        filing_type: str = "GST",
    ) -> FilingRecord | None:
        """Find the most recent 'changes_requested' filing for a user."""
        stmt = (
            select(FilingRecord)
            .where(
                FilingRecord.user_id == user_id,
                FilingRecord.filing_type == filing_type,
                FilingRecord.status == "changes_requested",
            )
            .order_by(FilingRecord.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def resubmit_with_payload(
        self,
        record_id: uuid.UUID,
        payload: dict,
    ) -> FilingRecord | None:
        """Update payload and transition from changes_requested -> pending_ca_review."""
        record = await self.get_by_id(record_id)
        if not record:
            return None
        record.payload_json = json.dumps(payload, default=str)
        record.status = "pending_ca_review"
        record.ca_notes = None
        record.ca_reviewed_at = None
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def find_ca_for_whatsapp(self, whatsapp_number: str) -> int | None:
        """
        Find the CA assigned to a WhatsApp user via BusinessClient table.

        Returns ca_id or None.
        """
        stmt = select(BusinessClient.ca_id).where(
            BusinessClient.whatsapp_number == whatsapp_number,
            BusinessClient.status == "active",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
