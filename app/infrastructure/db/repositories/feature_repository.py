# app/infrastructure/db/repositories/feature_repository.py
"""
Repository for Feature, SegmentFeature, and ClientAddon CRUD.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    BusinessClient,
    ClientAddon,
    Feature,
    SegmentFeature,
)


class FeatureRepository:
    """Data access for segment-based feature gating."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all_features(self) -> list[Feature]:
        """List all features ordered by display_order."""
        stmt = select(Feature).order_by(Feature.display_order)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> Feature | None:
        """Get a single feature by its code."""
        stmt = select(Feature).where(Feature.code == code)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_segment_features(self, segment: str) -> list[Feature]:
        """Get features enabled for a specific segment."""
        stmt = (
            select(Feature)
            .join(SegmentFeature, SegmentFeature.feature_id == Feature.id)
            .where(
                SegmentFeature.segment == segment,
                SegmentFeature.enabled.is_(True),
                Feature.is_active.is_(True),
            )
            .order_by(Feature.display_order)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_segment_features(
        self, segment: str, feature_codes: list[str]
    ) -> None:
        """Replace all features for a segment with the given codes."""
        # Delete existing
        del_stmt = delete(SegmentFeature).where(SegmentFeature.segment == segment)
        await self.db.execute(del_stmt)

        # Get feature IDs for requested codes
        if feature_codes:
            feat_stmt = select(Feature).where(Feature.code.in_(feature_codes))
            feat_result = await self.db.execute(feat_stmt)
            features = feat_result.scalars().all()

            for feat in features:
                sf = SegmentFeature(
                    segment=segment,
                    feature_id=feat.id,
                    enabled=True,
                )
                self.db.add(sf)

        await self.db.flush()

    async def get_client_addons(self, client_id: int) -> list[Feature]:
        """Get addon features granted to a specific client."""
        stmt = (
            select(Feature)
            .join(ClientAddon, ClientAddon.feature_id == Feature.id)
            .where(
                ClientAddon.client_id == client_id,
                ClientAddon.enabled.is_(True),
            )
            .order_by(Feature.display_order)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def add_client_addon(
        self,
        client_id: int,
        feature_code: str,
        granted_by: str = "admin",
    ) -> ClientAddon | None:
        """Grant a feature addon to a client. Returns None if feature not found."""
        feature = await self.get_by_code(feature_code)
        if not feature:
            return None

        # Check if already exists
        existing_stmt = select(ClientAddon).where(
            ClientAddon.client_id == client_id,
            ClientAddon.feature_id == feature.id,
        )
        existing_result = await self.db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.enabled = True
            existing.granted_by = granted_by
            await self.db.flush()
            return existing

        addon = ClientAddon(
            client_id=client_id,
            feature_id=feature.id,
            enabled=True,
            granted_by=granted_by,
        )
        self.db.add(addon)
        await self.db.flush()
        return addon

    async def remove_client_addon(
        self, client_id: int, feature_code: str
    ) -> bool:
        """Remove a feature addon from a client. Returns True if removed."""
        feature = await self.get_by_code(feature_code)
        if not feature:
            return False

        stmt = delete(ClientAddon).where(
            ClientAddon.client_id == client_id,
            ClientAddon.feature_id == feature.id,
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount > 0

    async def get_segment_stats(self) -> dict[str, int]:
        """Count clients per segment."""
        from sqlalchemy import func as sa_func

        stmt = (
            select(BusinessClient.segment, sa_func.count(BusinessClient.id))
            .group_by(BusinessClient.segment)
        )
        result = await self.db.execute(stmt)
        return dict(result.all())
