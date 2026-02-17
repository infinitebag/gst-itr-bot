# app/infrastructure/db/repositories/ml_model_repository.py
"""Repository for ML model artifacts — store, activate, load, list."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import MLModelArtifact, RiskAssessment


class MLModelRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store_model(
        self,
        model_name: str,
        model_binary: bytes,
        training_samples: int,
        accuracy: float | None = None,
        f1_macro: float | None = None,
        metrics_json: str | None = None,
        feature_names_json: str | None = None,
    ) -> MLModelArtifact:
        """Store a new model artifact (auto-increments version)."""
        # Get next version
        stmt = (
            select(func.coalesce(func.max(MLModelArtifact.version), 0))
            .where(MLModelArtifact.model_name == model_name)
        )
        result = await self.db.execute(stmt)
        current_max = result.scalar_one()
        next_version = current_max + 1

        artifact = MLModelArtifact(
            id=uuid.uuid4(),
            model_name=model_name,
            version=next_version,
            is_active=False,
            model_binary=model_binary,
            model_size_bytes=len(model_binary),
            training_samples=training_samples,
            accuracy=accuracy,
            f1_macro=f1_macro,
            metrics_json=metrics_json,
            feature_names_json=feature_names_json,
            trained_at=datetime.now(timezone.utc),
        )
        self.db.add(artifact)
        await self.db.commit()
        await self.db.refresh(artifact)
        return artifact

    async def activate_model(self, artifact_id: uuid.UUID) -> MLModelArtifact | None:
        """Activate a specific model version, deactivating all others of same name."""
        # Get the target artifact
        stmt = select(MLModelArtifact).where(MLModelArtifact.id == artifact_id)
        result = await self.db.execute(stmt)
        artifact = result.scalar_one_or_none()
        if not artifact:
            return None

        # Deactivate all models with the same name
        deactivate_stmt = (
            update(MLModelArtifact)
            .where(
                and_(
                    MLModelArtifact.model_name == artifact.model_name,
                    MLModelArtifact.is_active == True,  # noqa: E712
                )
            )
            .values(is_active=False)
        )
        await self.db.execute(deactivate_stmt)

        # Activate the target
        artifact.is_active = True
        await self.db.commit()
        await self.db.refresh(artifact)
        return artifact

    async def get_active_model(
        self, model_name: str = "risk_scoring_v1",
    ) -> MLModelArtifact | None:
        """Get the currently active model for a given name."""
        stmt = (
            select(MLModelArtifact)
            .where(
                and_(
                    MLModelArtifact.model_name == model_name,
                    MLModelArtifact.is_active == True,  # noqa: E712
                )
            )
            .order_by(MLModelArtifact.version.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_models(
        self,
        model_name: str = "risk_scoring_v1",
        limit: int = 10,
    ) -> list[MLModelArtifact]:
        """List model versions, most recent first (without binary data)."""
        stmt = (
            select(MLModelArtifact)
            .where(MLModelArtifact.model_name == model_name)
            .order_by(MLModelArtifact.version.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_new_labels_since(self, since: datetime) -> int:
        """Count RiskAssessment records with CA outcomes added since a timestamp."""
        stmt = (
            select(func.count(RiskAssessment.id))
            .where(
                and_(
                    RiskAssessment.ca_final_outcome.is_not(None),
                    RiskAssessment.updated_at >= since,
                )
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one() or 0
