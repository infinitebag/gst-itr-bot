# app/infrastructure/db/repositories/risk_assessment_repository.py
"""Repository for RiskAssessment CRUD, CA overrides, and outcome tracking."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import RiskAssessment


class RiskAssessmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_or_update(
        self,
        period_id: uuid.UUID,
        assessment: dict[str, Any],
    ) -> RiskAssessment:
        """Create or update a risk assessment for a period (upsert by period_id)."""
        stmt = select(RiskAssessment).where(
            RiskAssessment.period_id == period_id
        )
        result = await self.db.execute(stmt)
        ra = result.scalar_one_or_none()

        if ra is None:
            ra = RiskAssessment(
                id=uuid.uuid4(),
                period_id=period_id,
            )
            self.db.add(ra)

        # Overall
        ra.risk_score = assessment.get("risk_score", 0)
        ra.risk_level = assessment.get("risk_level", "LOW")

        # JSON fields
        if "risk_flags" in assessment:
            ra.risk_flags = json.dumps(assessment["risk_flags"])
        if "recommended_actions" in assessment:
            ra.recommended_actions = json.dumps(assessment["recommended_actions"])

        # Category scores
        ra.category_a_score = assessment.get("category_a_score", 0)
        ra.category_b_score = assessment.get("category_b_score", 0)
        ra.category_c_score = assessment.get("category_c_score", 0)
        ra.category_d_score = assessment.get("category_d_score", 0)
        ra.category_e_score = assessment.get("category_e_score", 0)

        # ML scoring fields (Phase 3B)
        if "ml_risk_score" in assessment:
            ra.ml_risk_score = assessment["ml_risk_score"]
        if "ml_prediction_json" in assessment:
            ra.ml_prediction_json = assessment["ml_prediction_json"]
        if "blend_weight" in assessment:
            ra.blend_weight = assessment["blend_weight"]

        ra.computed_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(ra)
        return ra

    async def get_by_period(self, period_id: uuid.UUID) -> RiskAssessment | None:
        """Get risk assessment for a period."""
        stmt = select(RiskAssessment).where(
            RiskAssessment.period_id == period_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, assessment_id: uuid.UUID) -> RiskAssessment | None:
        stmt = select(RiskAssessment).where(RiskAssessment.id == assessment_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def ca_override(
        self,
        assessment_id: uuid.UUID,
        override_score: int,
        notes: str | None = None,
    ) -> RiskAssessment | None:
        """CA overrides the computed risk score with a manual assessment."""
        ra = await self.get_by_id(assessment_id)
        if not ra:
            return None
        ra.ca_override_score = override_score
        ra.ca_override_notes = notes
        await self.db.commit()
        await self.db.refresh(ra)
        return ra

    async def record_outcome(
        self,
        assessment_id: uuid.UUID,
        ca_outcome: str | None = None,
        filing_outcome: str | None = None,
    ) -> RiskAssessment | None:
        """Record CA review outcome and/or post-filing outcome for calibration."""
        ra = await self.get_by_id(assessment_id)
        if not ra:
            return None
        if ca_outcome is not None:
            ra.ca_final_outcome = ca_outcome
        if filing_outcome is not None:
            ra.post_filing_outcome = filing_outcome
        await self.db.commit()
        await self.db.refresh(ra)

        # Auto-ingest CA precedent for future RAG retrieval
        if ca_outcome is not None:
            try:
                from app.domain.services.knowledge_ingestion import ingest_ca_precedent

                await ingest_ca_precedent(assessment_id, self.db)
            except Exception:
                import logging
                logging.getLogger("repo.risk_assessment").warning(
                    "CA precedent ingestion failed for %s", assessment_id
                )

        return ra
