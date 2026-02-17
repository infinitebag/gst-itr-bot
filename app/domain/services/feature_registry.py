# app/domain/services/feature_registry.py
"""
Feature registry service for segment-based gating.

Resolves which features a client can access based on their segment
plus any individual addons.  Results are cached in Redis.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings

logger = logging.getLogger("feature_registry")

# All 14 GST features in display order (fallback when gating disabled or DB unreachable)
_ALL_FEATURES: list[dict[str, Any]] = [
    {"code": "enter_gstin",        "name": "Enter GSTIN",        "display_order": 10, "whatsapp_state": "WAIT_GSTIN",         "i18n_key": "GST_MENU_ITEM_enter_gstin",        "category": "gst"},
    {"code": "monthly_compliance", "name": "Monthly Filing",     "display_order": 20, "whatsapp_state": "GST_PERIOD_MENU",    "i18n_key": "GST_MENU_ITEM_monthly_compliance", "category": "gst"},
    {"code": "filing_status",      "name": "Filing Status",      "display_order": 25, "whatsapp_state": "GST_FILING_STATUS",  "i18n_key": "GST_MENU_ITEM_filing_status",      "category": "gst"},
    {"code": "nil_return",         "name": "Zero Return",        "display_order": 30, "whatsapp_state": "NIL_FILING_MENU",    "i18n_key": "GST_MENU_ITEM_nil_return",         "category": "gst"},
    {"code": "upload_invoices",    "name": "Scan Invoices",      "display_order": 40, "whatsapp_state": "SMART_UPLOAD",       "i18n_key": "GST_MENU_ITEM_upload_invoices",    "category": "gst"},
    {"code": "credit_check",       "name": "Credit Check",       "display_order": 45, "whatsapp_state": "MEDIUM_CREDIT_CHECK","i18n_key": "GST_MENU_ITEM_credit_check",       "category": "gst"},
    {"code": "e_invoice",          "name": "e-Invoice",          "display_order": 50, "whatsapp_state": "EINVOICE_MENU",      "i18n_key": "GST_MENU_ITEM_e_invoice",          "category": "gst"},
    {"code": "e_waybill",          "name": "e-WayBill",          "display_order": 60, "whatsapp_state": "EWAYBILL_MENU",      "i18n_key": "GST_MENU_ITEM_e_waybill",          "category": "gst"},
    {"code": "annual_return",      "name": "Annual Summary",     "display_order": 70, "whatsapp_state": "GST_ANNUAL_MENU",    "i18n_key": "GST_MENU_ITEM_annual_return",      "category": "gst"},
    {"code": "risk_scoring",       "name": "Risk Check",         "display_order": 80, "whatsapp_state": "GST_RISK_REVIEW",    "i18n_key": "GST_MENU_ITEM_risk_scoring",       "category": "gst"},
    {"code": "multi_gstin",        "name": "Multi-GSTIN",        "display_order": 90, "whatsapp_state": "MULTI_GSTIN_MENU",   "i18n_key": "GST_MENU_ITEM_multi_gstin",        "category": "gst"},
    {"code": "refund_tracking",    "name": "Refund Tracking",    "display_order": 92, "whatsapp_state": "REFUND_MENU",        "i18n_key": "GST_MENU_ITEM_refund_tracking",    "category": "gst"},
    {"code": "notice_mgmt",        "name": "Notice Management",  "display_order": 94, "whatsapp_state": "NOTICE_MENU",        "i18n_key": "GST_MENU_ITEM_notice_mgmt",        "category": "gst"},
    {"code": "export_services",    "name": "Export Services",    "display_order": 96, "whatsapp_state": "EXPORT_MENU",        "i18n_key": "GST_MENU_ITEM_export_services",    "category": "gst"},
]


def _feature_to_dict(f) -> dict[str, Any]:
    """Convert a Feature ORM object to a plain dict."""
    return {
        "code": f.code,
        "name": f.name,
        "display_order": f.display_order,
        "whatsapp_state": f.whatsapp_state,
        "i18n_key": f.i18n_key,
        "category": f.category,
    }


async def get_features_for_segment(segment: str, db: AsyncSession) -> list[dict[str, Any]]:
    """Get features enabled for a segment (no addons)."""
    from app.infrastructure.db.models import Feature, SegmentFeature

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
    result = await db.execute(stmt)
    features = result.scalars().all()
    return [_feature_to_dict(f) for f in features]


async def get_features_for_client(client_id: int, db: AsyncSession) -> list[dict[str, Any]]:
    """Get all enabled features for a client (segment + addons), ordered by display_order."""
    from app.infrastructure.db.models import BusinessClient, ClientAddon, Feature, SegmentFeature

    # 1. Get client's segment
    client_stmt = select(BusinessClient.segment).where(BusinessClient.id == client_id)
    client_result = await db.execute(client_stmt)
    segment = client_result.scalar_one_or_none()
    if not segment:
        logger.warning("get_features_for_client: client_id=%d not found, using default", client_id)
        segment = settings.DEFAULT_SEGMENT

    # 2. Get segment features
    seg_stmt = (
        select(Feature)
        .join(SegmentFeature, SegmentFeature.feature_id == Feature.id)
        .where(
            SegmentFeature.segment == segment,
            SegmentFeature.enabled.is_(True),
            Feature.is_active.is_(True),
        )
    )
    seg_result = await db.execute(seg_stmt)
    seg_features = {f.code: f for f in seg_result.scalars().all()}

    # 3. Get addon features
    addon_stmt = (
        select(Feature)
        .join(ClientAddon, ClientAddon.feature_id == Feature.id)
        .where(
            ClientAddon.client_id == client_id,
            ClientAddon.enabled.is_(True),
            Feature.is_active.is_(True),
        )
    )
    addon_result = await db.execute(addon_stmt)
    for f in addon_result.scalars().all():
        if f.code not in seg_features:
            seg_features[f.code] = f

    # 4. Sort by display_order
    all_features = sorted(seg_features.values(), key=lambda f: f.display_order)
    return [_feature_to_dict(f) for f in all_features]


async def is_feature_enabled(client_id: int, feature_code: str, db: AsyncSession) -> bool:
    """Check if a specific feature is enabled for a client."""
    features = await get_cached_features(client_id, db)
    return any(f["code"] == feature_code for f in features)


async def get_cached_features(client_id: int, db: AsyncSession) -> list[dict[str, Any]]:
    """Redis-cached version of get_features_for_client.

    Key: ``seg:features:{client_id}``, TTL from settings.SEGMENT_CACHE_TTL.
    """
    if not settings.SEGMENT_GATING_ENABLED:
        return list(_ALL_FEATURES)

    cache_key = f"seg:features:{client_id}"

    try:
        from app.infrastructure.cache.session_cache import _redis_pool
        redis = await _redis_pool()
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        logger.debug("Redis cache miss/error for %s", cache_key)

    # Cache miss — query DB
    features = await get_features_for_client(client_id, db)

    # Store in Redis
    try:
        from app.infrastructure.cache.session_cache import _redis_pool
        redis = await _redis_pool()
        await redis.set(
            cache_key,
            json.dumps(features),
            ex=settings.SEGMENT_CACHE_TTL,
        )
    except Exception:
        logger.debug("Failed to cache features for client_id=%d", client_id)

    return features


async def invalidate_feature_cache(client_id: int) -> None:
    """Clear Redis cache for a client's features."""
    cache_key = f"seg:features:{client_id}"
    try:
        from app.infrastructure.cache.session_cache import _redis_pool
        redis = await _redis_pool()
        await redis.delete(cache_key)
    except Exception:
        logger.debug("Failed to invalidate cache for %s", cache_key)


def get_all_features_fallback() -> list[dict[str, Any]]:
    """Return all features (used when gating is disabled)."""
    return list(_ALL_FEATURES)
