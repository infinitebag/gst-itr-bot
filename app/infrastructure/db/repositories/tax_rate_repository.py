# app/infrastructure/db/repositories/tax_rate_repository.py
"""Repository for versioned tax rate configuration storage."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import TaxRateConfig


class TaxRateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active(
        self,
        rate_type: str,
        assessment_year: str | None = None,
    ) -> TaxRateConfig | None:
        """Get the current active config for a rate_type + assessment_year."""
        conditions = [
            TaxRateConfig.rate_type == rate_type,
            TaxRateConfig.is_active.is_(True),
        ]
        if assessment_year:
            conditions.append(TaxRateConfig.assessment_year == assessment_year)
        else:
            conditions.append(TaxRateConfig.assessment_year.is_(None))

        stmt = (
            select(TaxRateConfig)
            .where(and_(*conditions))
            .order_by(TaxRateConfig.version.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def save_config(
        self,
        rate_type: str,
        config_json: str,
        source: str,
        assessment_year: str | None = None,
        created_by: str = "system",
        notes: str | None = None,
    ) -> TaxRateConfig:
        """Save a new config version. Deactivates previous active config."""
        # Get current max version
        conditions = [TaxRateConfig.rate_type == rate_type]
        if assessment_year:
            conditions.append(TaxRateConfig.assessment_year == assessment_year)
        else:
            conditions.append(TaxRateConfig.assessment_year.is_(None))

        stmt = (
            select(TaxRateConfig.version)
            .where(and_(*conditions))
            .order_by(TaxRateConfig.version.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        max_version = result.scalar_one_or_none() or 0

        # Deactivate previous active configs
        deactivate_conditions = [
            TaxRateConfig.rate_type == rate_type,
            TaxRateConfig.is_active.is_(True),
        ]
        if assessment_year:
            deactivate_conditions.append(TaxRateConfig.assessment_year == assessment_year)
        else:
            deactivate_conditions.append(TaxRateConfig.assessment_year.is_(None))

        deactivate = (
            update(TaxRateConfig)
            .where(and_(*deactivate_conditions))
            .values(is_active=False)
        )
        await self.db.execute(deactivate)

        # Insert new version
        record = TaxRateConfig(
            id=uuid.uuid4(),
            rate_type=rate_type,
            assessment_year=assessment_year,
            config_json=config_json,
            source=source,
            version=max_version + 1,
            is_active=True,
            created_by=created_by,
            notes=notes,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def list_versions(
        self,
        rate_type: str,
        assessment_year: str | None = None,
        limit: int = 20,
    ) -> list[TaxRateConfig]:
        """List config version history (newest first)."""
        conditions = [TaxRateConfig.rate_type == rate_type]
        if assessment_year:
            conditions.append(TaxRateConfig.assessment_year == assessment_year)

        stmt = (
            select(TaxRateConfig)
            .where(and_(*conditions))
            .order_by(TaxRateConfig.version.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
