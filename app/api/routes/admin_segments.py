# app/api/routes/admin_segments.py
"""
Admin endpoints for segment-based feature gating management.

All endpoints require admin authentication via X-Admin-Token header
or admin_session cookie.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token
from app.core.db import get_db

logger = logging.getLogger("admin.segments")

router = APIRouter(prefix="/admin/segments", tags=["admin-segments"])


# ---- Request/Response schemas ----


class SegmentFeaturesUpdate(BaseModel):
    feature_codes: list[str]


class ClientSegmentUpdate(BaseModel):
    segment: str  # "small" / "medium" / "enterprise"


class ClientAddonRequest(BaseModel):
    feature_code: str
    granted_by: str = "admin"


# ---- Endpoints ----


@router.get(
    "/features",
    summary="List all features",
    dependencies=[Depends(require_admin_token)],
)
async def list_all_features(
    db: AsyncSession = Depends(get_db),
):
    """List all features in the registry."""
    from app.infrastructure.db.repositories.feature_repository import FeatureRepository

    repo = FeatureRepository(db)
    features = await repo.get_all_features()
    return {
        "status": "ok",
        "data": [
            {
                "id": f.id,
                "code": f.code,
                "name": f.name,
                "category": f.category,
                "display_order": f.display_order,
                "whatsapp_state": f.whatsapp_state,
                "i18n_key": f.i18n_key,
                "is_active": f.is_active,
            }
            for f in features
        ],
    }


@router.get(
    "/{segment}/features",
    summary="List features for a segment",
    dependencies=[Depends(require_admin_token)],
)
async def list_segment_features(
    segment: str,
    db: AsyncSession = Depends(get_db),
):
    """List features enabled for a specific segment."""
    if segment not in ("small", "medium", "enterprise"):
        raise HTTPException(status_code=400, detail="Invalid segment. Use small/medium/enterprise.")

    from app.infrastructure.db.repositories.feature_repository import FeatureRepository

    repo = FeatureRepository(db)
    features = await repo.get_segment_features(segment)
    return {
        "status": "ok",
        "data": {
            "segment": segment,
            "features": [
                {
                    "id": f.id,
                    "code": f.code,
                    "name": f.name,
                    "display_order": f.display_order,
                }
                for f in features
            ],
            "count": len(features),
        },
    }


@router.put(
    "/{segment}/features",
    summary="Update segment feature mapping",
    dependencies=[Depends(require_admin_token)],
)
async def update_segment_features(
    segment: str,
    body: SegmentFeaturesUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Replace features for a segment with the given codes."""
    if segment not in ("small", "medium", "enterprise"):
        raise HTTPException(status_code=400, detail="Invalid segment. Use small/medium/enterprise.")

    from app.infrastructure.db.repositories.feature_repository import FeatureRepository

    repo = FeatureRepository(db)
    await repo.set_segment_features(segment, body.feature_codes)
    await db.commit()

    # Re-fetch to confirm
    features = await repo.get_segment_features(segment)
    return {
        "status": "ok",
        "data": {
            "segment": segment,
            "features": [f.code for f in features],
            "count": len(features),
        },
    }


@router.get(
    "/clients/{client_id}",
    summary="Client segment info + enabled features",
    dependencies=[Depends(require_admin_token)],
)
async def get_client_segment(
    client_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a client's segment, enabled features, and addons."""
    from sqlalchemy import select

    from app.domain.services.feature_registry import get_features_for_client
    from app.infrastructure.db.models import BusinessClient
    from app.infrastructure.db.repositories.feature_repository import FeatureRepository

    # Get client
    stmt = select(BusinessClient).where(BusinessClient.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Get enabled features
    features = await get_features_for_client(client_id, db)

    # Get addons
    repo = FeatureRepository(db)
    addons = await repo.get_client_addons(client_id)

    return {
        "status": "ok",
        "data": {
            "client_id": client_id,
            "name": client.name,
            "gstin": client.gstin,
            "segment": client.segment,
            "segment_override": client.segment_override,
            "annual_turnover": float(client.annual_turnover) if client.annual_turnover else None,
            "monthly_invoice_volume": client.monthly_invoice_volume,
            "gstin_count": client.gstin_count,
            "is_exporter": client.is_exporter,
            "features": [f["code"] for f in features],
            "feature_count": len(features),
            "addons": [a.code for a in addons],
        },
    }


@router.put(
    "/clients/{client_id}",
    summary="Update client segment (override)",
    dependencies=[Depends(require_admin_token)],
)
async def update_client_segment(
    client_id: int,
    body: ClientSegmentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Manually set a client's segment (sets segment_override=True)."""
    if body.segment not in ("small", "medium", "enterprise"):
        raise HTTPException(status_code=400, detail="Invalid segment. Use small/medium/enterprise.")

    from sqlalchemy import select

    from app.domain.services.feature_registry import invalidate_feature_cache
    from app.infrastructure.db.models import BusinessClient

    stmt = select(BusinessClient).where(BusinessClient.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    old_segment = client.segment
    client.segment = body.segment
    client.segment_override = True
    await db.commit()

    await invalidate_feature_cache(client_id)

    return {
        "status": "ok",
        "data": {
            "client_id": client_id,
            "old_segment": old_segment,
            "new_segment": body.segment,
            "segment_override": True,
        },
    }


@router.post(
    "/clients/{client_id}/addon",
    summary="Add feature addon to client",
    dependencies=[Depends(require_admin_token)],
)
async def add_client_addon(
    client_id: int,
    body: ClientAddonRequest,
    db: AsyncSession = Depends(get_db),
):
    """Grant a feature addon beyond the client's segment defaults."""
    from app.domain.services.feature_registry import invalidate_feature_cache
    from app.infrastructure.db.repositories.feature_repository import FeatureRepository

    repo = FeatureRepository(db)
    addon = await repo.add_client_addon(client_id, body.feature_code, body.granted_by)
    if not addon:
        raise HTTPException(status_code=404, detail=f"Feature '{body.feature_code}' not found")

    await db.commit()
    await invalidate_feature_cache(client_id)

    return {
        "status": "ok",
        "data": {
            "client_id": client_id,
            "feature_code": body.feature_code,
            "granted_by": body.granted_by,
        },
    }


@router.delete(
    "/clients/{client_id}/addon/{code}",
    summary="Remove feature addon from client",
    dependencies=[Depends(require_admin_token)],
)
async def remove_client_addon(
    client_id: int,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Remove a feature addon from a client."""
    from app.domain.services.feature_registry import invalidate_feature_cache
    from app.infrastructure.db.repositories.feature_repository import FeatureRepository

    repo = FeatureRepository(db)
    removed = await repo.remove_client_addon(client_id, code)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Addon '{code}' not found for client")

    await db.commit()
    await invalidate_feature_cache(client_id)

    return {"status": "ok", "data": {"client_id": client_id, "removed": code}}


@router.post(
    "/auto-detect/{client_id}",
    summary="Re-run auto-detection for a client",
    dependencies=[Depends(require_admin_token)],
)
async def auto_detect_segment(
    client_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Re-run segment auto-detection for a client."""
    from app.domain.services.segment_detection import auto_segment_client

    new_segment = await auto_segment_client(client_id, db)
    await db.commit()

    return {
        "status": "ok",
        "data": {
            "client_id": client_id,
            "segment": new_segment,
        },
    }


@router.get(
    "/stats",
    summary="Segment distribution stats",
    dependencies=[Depends(require_admin_token)],
)
async def segment_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get the count of clients per segment."""
    from app.infrastructure.db.repositories.feature_repository import FeatureRepository

    repo = FeatureRepository(db)
    stats = await repo.get_segment_stats()

    return {
        "status": "ok",
        "data": {
            "by_segment": stats,
            "total_clients": sum(stats.values()),
        },
    }
