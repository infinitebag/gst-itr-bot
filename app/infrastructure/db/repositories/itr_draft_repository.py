# app/infrastructure/db/repositories/itr_draft_repository.py
"""
Repository for ITR draft CRUD operations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import ITRDraft, BusinessClient

logger = logging.getLogger("itr_draft_repository")


class ITRDraftRepository:
    """Async repository for ITRDraft records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        user_id: UUID,
        form_type: str,
        assessment_year: str,
        pan: str | None = None,
        ca_id: int | None = None,
        status: str = "draft",
        input_json: str | None = None,
        result_json: str | None = None,
        merged_data_json: str | None = None,
        mismatch_json: str | None = None,
        checklist_json: str | None = None,
        linked_gst_filing_ids: list[str] | None = None,
    ) -> ITRDraft:
        """Create a new ITR draft."""
        draft = ITRDraft(
            user_id=user_id,
            form_type=form_type,
            assessment_year=assessment_year,
            pan=pan,
            ca_id=ca_id,
            status=status,
            input_json=input_json,
            result_json=result_json,
            merged_data_json=merged_data_json,
            mismatch_json=mismatch_json,
            checklist_json=checklist_json,
            linked_gst_filing_ids=(
                json.dumps(linked_gst_filing_ids) if linked_gst_filing_ids else None
            ),
        )
        self.db.add(draft)
        await self.db.flush()
        return draft

    async def get_by_id(self, draft_id: UUID) -> ITRDraft | None:
        """Fetch a draft by its ID."""
        stmt = select(ITRDraft).where(ITRDraft.id == draft_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user(
        self, user_id: UUID, limit: int = 20
    ) -> list[ITRDraft]:
        """List drafts for a user, most recent first."""
        stmt = (
            select(ITRDraft)
            .where(ITRDraft.user_id == user_id)
            .order_by(ITRDraft.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_for_ca(self, ca_id: int) -> list[ITRDraft]:
        """
        List all drafts pending review for a specific CA.

        This finds drafts where:
        1. ca_id matches directly, OR
        2. The user is a client of this CA (via BusinessClient)
        and status is 'pending_ca_review'.
        """
        # Direct CA assignment
        stmt = (
            select(ITRDraft)
            .where(
                ITRDraft.ca_id == ca_id,
                ITRDraft.status == "pending_ca_review",
            )
            .order_by(ITRDraft.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_for_ca(
        self, ca_id: int, status: str | None = None
    ) -> list[ITRDraft]:
        """List all ITR drafts for a CA's clients (any status)."""
        stmt = select(ITRDraft).where(ITRDraft.ca_id == ca_id)
        if status:
            stmt = stmt.where(ITRDraft.status == status)
        stmt = stmt.order_by(ITRDraft.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_for_client_user(
        self, user_id: UUID, limit: int = 20
    ) -> list[ITRDraft]:
        """List all ITR drafts for a specific client user."""
        stmt = (
            select(ITRDraft)
            .where(ITRDraft.user_id == user_id)
            .order_by(ITRDraft.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        draft_id: UUID,
        status: str,
        *,
        ca_notes: str | None = None,
        ca_reviewed_at: datetime | None = None,
        filing_record_id: UUID | None = None,
    ) -> ITRDraft | None:
        """Update draft status and optional CA review fields."""
        draft = await self.get_by_id(draft_id)
        if not draft:
            return None

        draft.status = status
        if ca_notes is not None:
            draft.ca_notes = ca_notes
        if ca_reviewed_at is not None:
            draft.ca_reviewed_at = ca_reviewed_at
        if filing_record_id is not None:
            draft.filing_record_id = filing_record_id

        await self.db.flush()
        return draft

    async def update_fields(
        self,
        draft_id: UUID,
        *,
        input_json: str | None = None,
        result_json: str | None = None,
        merged_data_json: str | None = None,
        mismatch_json: str | None = None,
        checklist_json: str | None = None,
    ) -> ITRDraft | None:
        """Update computation data fields on a draft (e.g., after CA edits)."""
        draft = await self.get_by_id(draft_id)
        if not draft:
            return None

        if input_json is not None:
            draft.input_json = input_json
        if result_json is not None:
            draft.result_json = result_json
        if merged_data_json is not None:
            draft.merged_data_json = merged_data_json
        if mismatch_json is not None:
            draft.mismatch_json = mismatch_json
        if checklist_json is not None:
            draft.checklist_json = checklist_json

        await self.db.flush()
        return draft

    async def get_unassigned_drafts(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ITRDraft], int]:
        """
        Return ITR drafts where ca_id IS NULL and status is 'pending_ca_review'.
        Returns (drafts, total_count).
        """
        base = select(ITRDraft).where(
            ITRDraft.ca_id.is_(None),
            ITRDraft.status == "pending_ca_review",
        )
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one() or 0

        stmt = base.order_by(ITRDraft.created_at.asc()).offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def assign_ca(
        self,
        draft_id: UUID,
        ca_id: int,
    ) -> ITRDraft | None:
        """Assign a CA to an unassigned ITR draft."""
        draft = await self.get_by_id(draft_id)
        if not draft:
            return None
        draft.ca_id = ca_id
        await self.db.flush()
        return draft

    async def find_ca_for_user(self, whatsapp_number: str) -> int | None:
        """
        Find the CA assigned to a WhatsApp user via BusinessClient table.

        Returns ca_id or None.
        """
        stmt = select(BusinessClient.ca_id).where(
            BusinessClient.whatsapp_number == whatsapp_number,
            BusinessClient.status == "active",
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return row
