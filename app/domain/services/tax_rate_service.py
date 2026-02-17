# app/domain/services/tax_rate_service.py
"""
Dynamic Tax Rate Service — 3-layer resolution.

Resolution order:
1. Redis (hot cache, 24h TTL)
2. PostgreSQL (warm, versioned audit trail)
3. OpenAI GPT-4o (cold, AI fetch with validation)
4. Hardcoded defaults (final fallback — never fails)
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from app.config.settings import settings
from app.domain.models.tax_rate_config import GSTRateConfig, ITRSlabConfig
from app.domain.services.tax_rate_defaults import default_gst_rates, default_itr_slabs

logger = logging.getLogger("tax_rate_service")

_REDIS_TTL = 24 * 60 * 60  # 24 hours
_REDIS_KEY_PREFIX = "tax_rate:"


class TaxRateService:
    """3-layer resolution: Redis -> PostgreSQL -> OpenAI -> Hardcoded."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL, decode_responses=True,
            )
        return self._redis

    # ---- Redis keys ----

    @staticmethod
    def _itr_key(assessment_year: str) -> str:
        return f"{_REDIS_KEY_PREFIX}itr:{assessment_year}"

    @staticmethod
    def _gst_key() -> str:
        return f"{_REDIS_KEY_PREFIX}gst:rates"

    # ---- Layer 1: Redis (hot cache) ----

    async def _get_from_redis(self, key: str) -> dict | None:
        r = await self._get_redis()
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
        return None

    async def _set_in_redis(self, key: str, data: dict) -> None:
        r = await self._get_redis()
        await r.set(key, json.dumps(data, default=str), ex=_REDIS_TTL)

    # ---- Layer 2: PostgreSQL (warm, audit trail) ----

    async def _get_from_db(
        self, rate_type: str, assessment_year: str | None = None,
    ) -> dict | None:
        from app.core.db import AsyncSessionLocal
        from app.infrastructure.db.repositories.tax_rate_repository import (
            TaxRateRepository,
        )

        async with AsyncSessionLocal() as db:
            repo = TaxRateRepository(db)
            record = await repo.get_active(rate_type, assessment_year)
            if record:
                return json.loads(record.config_json)
        return None

    async def _save_to_db(
        self,
        rate_type: str,
        config_dict: dict,
        source: str,
        assessment_year: str | None = None,
        created_by: str = "system",
        notes: str | None = None,
    ) -> None:
        from app.core.db import AsyncSessionLocal
        from app.infrastructure.db.repositories.tax_rate_repository import (
            TaxRateRepository,
        )

        async with AsyncSessionLocal() as db:
            repo = TaxRateRepository(db)
            await repo.save_config(
                rate_type=rate_type,
                config_json=json.dumps(config_dict, default=str),
                source=source,
                assessment_year=assessment_year,
                created_by=created_by,
                notes=notes,
            )

    # ---- Layer 3: OpenAI (cold, AI fetch) ----

    async def _fetch_from_ai_itr(self, assessment_year: str) -> ITRSlabConfig | None:
        from app.infrastructure.external.tax_rate_ai import fetch_itr_slabs_from_ai

        config = await fetch_itr_slabs_from_ai(assessment_year)
        if config:
            d = config.to_dict()
            # Persist to DB and Redis
            try:
                await self._save_to_db(
                    "itr", d, "openai",
                    assessment_year=assessment_year,
                    created_by="openai_refresh",
                    notes=f"Auto-fetched via OpenAI for AY {assessment_year}",
                )
            except Exception:
                logger.exception("Failed to save AI ITR config to DB")
            try:
                await self._set_in_redis(self._itr_key(assessment_year), d)
            except Exception:
                logger.exception("Failed to cache AI ITR config in Redis")
        return config

    async def _fetch_from_ai_gst(self) -> GSTRateConfig | None:
        from app.infrastructure.external.tax_rate_ai import fetch_gst_rates_from_ai

        config = await fetch_gst_rates_from_ai()
        if config:
            d = config.to_dict()
            try:
                await self._save_to_db(
                    "gst", d, "openai",
                    created_by="openai_refresh",
                    notes="Auto-fetched via OpenAI",
                )
            except Exception:
                logger.exception("Failed to save AI GST config to DB")
            try:
                await self._set_in_redis(self._gst_key(), d)
            except Exception:
                logger.exception("Failed to cache AI GST config in Redis")
        return config

    # ---- Public API ----

    async def get_itr_slabs(self, assessment_year: str = "2025-26") -> ITRSlabConfig:
        """
        3-layer resolution for ITR slab config.

        Never raises — always returns a valid ITRSlabConfig.
        """
        key = self._itr_key(assessment_year)

        # Layer 1: Redis
        try:
            cached = await self._get_from_redis(key)
            if cached:
                logger.debug("ITR slabs cache HIT (Redis) for AY %s", assessment_year)
                return ITRSlabConfig.from_dict(cached)
        except Exception:
            logger.warning("Redis failed for ITR slabs AY %s, trying DB", assessment_year)

        # Layer 2: PostgreSQL
        try:
            db_data = await self._get_from_db("itr", assessment_year)
            if db_data:
                logger.debug("ITR slabs cache HIT (DB) for AY %s", assessment_year)
                config = ITRSlabConfig.from_dict(db_data)
                # Re-warm Redis
                try:
                    await self._set_in_redis(key, db_data)
                except Exception:
                    pass
                return config
        except Exception:
            logger.warning("DB failed for ITR slabs AY %s, trying OpenAI", assessment_year)

        # Layer 3: OpenAI
        try:
            ai_config = await self._fetch_from_ai_itr(assessment_year)
            if ai_config:
                logger.info("ITR slabs fetched from OpenAI for AY %s", assessment_year)
                return ai_config
        except Exception:
            logger.warning("OpenAI failed for ITR slabs AY %s, using hardcoded", assessment_year)

        # Layer 4: Hardcoded fallback
        logger.info("Using hardcoded ITR slabs for AY %s", assessment_year)
        return default_itr_slabs(assessment_year)

    async def get_gst_rates(self) -> GSTRateConfig:
        """
        3-layer resolution for GST rate config.

        Never raises — always returns a valid GSTRateConfig.
        """
        key = self._gst_key()

        # Layer 1: Redis
        try:
            cached = await self._get_from_redis(key)
            if cached:
                return GSTRateConfig.from_dict(cached)
        except Exception:
            logger.warning("Redis failed for GST rates, trying DB")

        # Layer 2: PostgreSQL
        try:
            db_data = await self._get_from_db("gst")
            if db_data:
                config = GSTRateConfig.from_dict(db_data)
                try:
                    await self._set_in_redis(key, db_data)
                except Exception:
                    pass
                return config
        except Exception:
            logger.warning("DB failed for GST rates, trying OpenAI")

        # Layer 3: OpenAI
        try:
            ai_config = await self._fetch_from_ai_gst()
            if ai_config:
                return ai_config
        except Exception:
            logger.warning("OpenAI failed for GST rates, using hardcoded")

        # Layer 4: Hardcoded fallback
        return default_gst_rates()

    async def refresh_itr_slabs(self, assessment_year: str = "2025-26") -> ITRSlabConfig:
        """Force OpenAI fetch + save to DB + Redis. Returns the new config."""
        config = await self._fetch_from_ai_itr(assessment_year)
        if config:
            return config
        # If AI fails, return current best available
        return await self.get_itr_slabs(assessment_year)

    async def refresh_gst_rates(self) -> GSTRateConfig:
        """Force OpenAI fetch + save to DB + Redis. Returns the new config."""
        config = await self._fetch_from_ai_gst()
        if config:
            return config
        return await self.get_gst_rates()

    async def save_manual_itr_config(
        self,
        assessment_year: str,
        config: ITRSlabConfig,
        notes: str = "",
    ) -> None:
        """Admin manual override — saves to DB + Redis."""
        config.source = "manual"
        d = config.to_dict()

        await self._save_to_db(
            "itr", d, "manual",
            assessment_year=assessment_year,
            created_by="admin",
            notes=notes or "Manual admin override",
        )
        try:
            await self._set_in_redis(self._itr_key(assessment_year), d)
        except Exception:
            logger.exception("Failed to update Redis after manual ITR override")

    async def save_manual_gst_config(
        self,
        config: GSTRateConfig,
        notes: str = "",
    ) -> None:
        """Admin manual override — saves to DB + Redis."""
        config.source = "manual"
        d = config.to_dict()

        await self._save_to_db(
            "gst", d, "manual",
            created_by="admin",
            notes=notes or "Manual admin override",
        )
        try:
            await self._set_in_redis(self._gst_key(), d)
        except Exception:
            logger.exception("Failed to update Redis after manual GST override")


# ---------------------------------------------------------------------------
# Module-level singleton (matches SessionCache pattern)
# ---------------------------------------------------------------------------

_service: TaxRateService | None = None


def get_tax_rate_service() -> TaxRateService:
    """Get the singleton TaxRateService instance."""
    global _service
    if _service is None:
        _service = TaxRateService()
    return _service
