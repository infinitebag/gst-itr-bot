# app/api/v1/routes/admin_tax_rates.py
"""
Admin endpoints for dynamic tax rate management.

Allows viewing current configs, triggering AI refresh, and manual overrides.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token
from app.api.v1.envelope import ok
from app.api.v1.schemas.tax_rates import (
    GSTRateOverride,
    ITRSlabOverride,
    RefreshRequest,
    TaxRateConfigOut,
)
from app.core.db import get_db
from app.domain.services.tax_rate_service import get_tax_rate_service
from app.infrastructure.audit import log_admin_action

logger = logging.getLogger("api.v1.admin_tax_rates")

router = APIRouter(prefix="/admin/tax-rates", tags=["Admin Tax Rates"])


# ---------------------------------------------------------------------------
# GET — current active configs
# ---------------------------------------------------------------------------


@router.get("/itr/{assessment_year}", response_model=dict)
async def get_current_itr_config(
    assessment_year: str,
    _: None = Depends(require_admin_token),
):
    """Get the current active ITR slab config for an assessment year."""
    service = get_tax_rate_service()
    config = await service.get_itr_slabs(assessment_year)
    return ok(data={
        "assessment_year": assessment_year,
        "config": config.to_dict(),
        "source": config.source,
    })


@router.get("/gst", response_model=dict)
async def get_current_gst_config(
    _: None = Depends(require_admin_token),
):
    """Get the current active GST rate config."""
    service = get_tax_rate_service()
    config = await service.get_gst_rates()
    return ok(data={
        "config": config.to_dict(),
        "source": config.source,
    })


# ---------------------------------------------------------------------------
# POST — AI refresh
# ---------------------------------------------------------------------------


@router.post("/itr/refresh", response_model=dict)
async def refresh_itr_slabs(
    body: RefreshRequest,
    _: None = Depends(require_admin_token),
):
    """Force OpenAI to fetch the latest ITR slabs and persist them."""
    service = get_tax_rate_service()
    config = await service.refresh_itr_slabs(body.assessment_year)
    log_admin_action(
        "refresh_itr_slabs", admin_ip="api",
        details={"ay": body.assessment_year, "source": config.source},
    )
    return ok(
        data=config.to_dict(),
        message=f"ITR slabs refreshed from {config.source}",
    )


@router.post("/gst/refresh", response_model=dict)
async def refresh_gst_rates(
    _: None = Depends(require_admin_token),
):
    """Force OpenAI to fetch the latest GST rates and persist them."""
    service = get_tax_rate_service()
    config = await service.refresh_gst_rates()
    log_admin_action(
        "refresh_gst_rates", admin_ip="api",
        details={"source": config.source},
    )
    return ok(
        data=config.to_dict(),
        message=f"GST rates refreshed from {config.source}",
    )


# ---------------------------------------------------------------------------
# PUT — manual admin overrides
# ---------------------------------------------------------------------------


@router.put("/itr/override", response_model=dict)
async def override_itr_slabs(
    body: ITRSlabOverride,
    _: None = Depends(require_admin_token),
):
    """Manually override ITR slabs (admin power)."""
    from app.domain.models.tax_rate_config import ITRSlabConfig

    try:
        config = ITRSlabConfig.from_dict(
            {**body.config, "assessment_year": body.assessment_year},
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid config: {e}")

    service = get_tax_rate_service()
    await service.save_manual_itr_config(
        body.assessment_year, config, notes=body.notes or "",
    )
    log_admin_action(
        "override_itr_slabs", admin_ip="api",
        details={"ay": body.assessment_year},
    )
    return ok(message="ITR slabs overridden manually")


@router.put("/gst/override", response_model=dict)
async def override_gst_rates(
    body: GSTRateOverride,
    _: None = Depends(require_admin_token),
):
    """Manually override GST rates (admin power)."""
    from app.domain.models.tax_rate_config import GSTRateConfig

    config = GSTRateConfig(valid_rates=set(body.valid_rates), source="manual")

    service = get_tax_rate_service()
    await service.save_manual_gst_config(config, notes=body.notes or "")
    log_admin_action(
        "override_gst_rates", admin_ip="api",
        details={"rates": body.valid_rates},
    )
    return ok(message="GST rates overridden manually")


# ---------------------------------------------------------------------------
# GET — version history
# ---------------------------------------------------------------------------


@router.get("/itr/{assessment_year}/history", response_model=dict)
async def get_itr_history(
    assessment_year: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """List version history for ITR slab configs."""
    from app.infrastructure.db.repositories.tax_rate_repository import (
        TaxRateRepository,
    )

    repo = TaxRateRepository(db)
    versions = await repo.list_versions("itr", assessment_year, limit=limit)
    items = [
        TaxRateConfigOut(
            id=str(v.id),
            rate_type=v.rate_type,
            assessment_year=v.assessment_year,
            config=json.loads(v.config_json),
            source=v.source,
            version=v.version,
            is_active=v.is_active,
            created_by=v.created_by,
            notes=v.notes,
            created_at=v.created_at,
        ).model_dump()
        for v in versions
    ]
    return ok(data=items)


@router.get("/gst/history", response_model=dict)
async def get_gst_history(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    """List version history for GST rate configs."""
    from app.infrastructure.db.repositories.tax_rate_repository import (
        TaxRateRepository,
    )

    repo = TaxRateRepository(db)
    versions = await repo.list_versions("gst", limit=limit)
    items = [
        TaxRateConfigOut(
            id=str(v.id),
            rate_type=v.rate_type,
            assessment_year=v.assessment_year,
            config=json.loads(v.config_json),
            source=v.source,
            version=v.version,
            is_active=v.is_active,
            created_by=v.created_by,
            notes=v.notes,
            created_at=v.created_at,
        ).model_dump()
        for v in versions
    ]
    return ok(data=items)
