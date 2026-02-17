# app/api/routes/admin_ml_risk.py
"""
Admin endpoints for ML-powered risk scoring management.

All endpoints require admin authentication via X-Admin-Token header
or admin_session cookie.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token
from app.core.db import get_db

logger = logging.getLogger("admin.ml_risk")

router = APIRouter(prefix="/admin/ml-risk", tags=["admin-ml-risk"])


@router.post(
    "/train",
    summary="Trigger ML model training",
    dependencies=[Depends(require_admin_token)],
)
async def train_model(
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger ML risk model training.

    Collects all CA-labeled risk assessments, trains a GradientBoosting
    model, and optionally auto-activates if quality exceeds the previous.
    """
    from app.domain.services.ml_training_pipeline import train_and_store

    try:
        result = await train_and_store(db, auto_activate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("ML training failed")
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", "data": result.to_dict()}


@router.get(
    "/status",
    summary="Active model info + cold start check",
    dependencies=[Depends(require_admin_token)],
)
async def ml_status(
    db: AsyncSession = Depends(get_db),
):
    """Get active ML model info and cold-start readiness."""
    from app.domain.services.ml_training_pipeline import check_cold_start
    from app.infrastructure.db.repositories.ml_model_repository import MLModelRepository

    repo = MLModelRepository(db)
    active = await repo.get_active_model("risk_scoring_v1")
    cold_start = await check_cold_start(db)

    active_info = None
    if active:
        active_info = {
            "model_id": str(active.id),
            "version": active.version,
            "training_samples": active.training_samples,
            "accuracy": active.accuracy,
            "f1_macro": active.f1_macro,
            "model_size_bytes": active.model_size_bytes,
            "trained_at": active.trained_at.isoformat() if active.trained_at else None,
        }

    return {
        "status": "ok",
        "data": {
            "active_model": active_info,
            "cold_start": cold_start,
            "ml_enabled": True,
        },
    }


@router.get(
    "/models",
    summary="List model versions + metrics",
    dependencies=[Depends(require_admin_token)],
)
async def list_models(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """List ML model versions with training metrics, most recent first."""
    from app.infrastructure.db.repositories.ml_model_repository import MLModelRepository

    repo = MLModelRepository(db)
    models = await repo.list_models("risk_scoring_v1", limit=limit)

    model_list = []
    for m in models:
        metrics = None
        if m.metrics_json:
            try:
                metrics = json.loads(m.metrics_json)
            except (ValueError, TypeError):
                pass

        model_list.append({
            "id": str(m.id),
            "version": m.version,
            "is_active": m.is_active,
            "training_samples": m.training_samples,
            "accuracy": m.accuracy,
            "f1_macro": m.f1_macro,
            "model_size_bytes": m.model_size_bytes,
            "trained_at": m.trained_at.isoformat() if m.trained_at else None,
            "metrics": metrics,
        })

    return {"status": "ok", "data": model_list}


@router.post(
    "/models/{model_id}/activate",
    summary="Activate a specific model version",
    dependencies=[Depends(require_admin_token)],
)
async def activate_model(
    model_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Activate a specific model version (deactivates all others)."""
    from app.infrastructure.db.repositories.ml_model_repository import MLModelRepository

    repo = MLModelRepository(db)
    artifact = await repo.activate_model(model_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Model not found")

    return {
        "status": "ok",
        "data": {
            "id": str(artifact.id),
            "version": artifact.version,
            "is_active": artifact.is_active,
            "accuracy": artifact.accuracy,
            "f1_macro": artifact.f1_macro,
        },
    }


@router.get(
    "/compare/{period_id}",
    summary="Side-by-side rule vs ML scores",
    dependencies=[Depends(require_admin_token)],
)
async def compare_scores(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Compare rule-based and ML risk scores for a period."""
    from app.infrastructure.db.repositories.risk_assessment_repository import (
        RiskAssessmentRepository,
    )

    repo = RiskAssessmentRepository(db)
    ra = await repo.get_by_period(period_id)
    if not ra:
        raise HTTPException(
            status_code=404,
            detail="Risk assessment not found. Compute risk first.",
        )

    ml_prediction = None
    if ra.ml_prediction_json:
        try:
            ml_prediction = json.loads(ra.ml_prediction_json)
        except (ValueError, TypeError):
            pass

    # The rule-only score can be derived: if blend_weight is known
    rule_only_score = ra.risk_score
    if ra.blend_weight and ra.blend_weight > 0 and ra.ml_risk_score is not None:
        # Reverse the blend: blended = (1-w)*rule + w*ml
        # rule = (blended - w*ml) / (1-w)
        try:
            rule_only_score = round(
                (ra.risk_score - ra.blend_weight * ra.ml_risk_score)
                / (1 - ra.blend_weight)
            )
            rule_only_score = max(0, min(100, rule_only_score))
        except ZeroDivisionError:
            pass

    return {
        "status": "ok",
        "data": {
            "period_id": str(period_id),
            "final_blended_score": ra.risk_score,
            "rule_only_score": rule_only_score,
            "ml_risk_score": ra.ml_risk_score,
            "blend_weight": ra.blend_weight,
            "risk_level": ra.risk_level,
            "ml_prediction": ml_prediction,
        },
    }


@router.get(
    "/feature-importance",
    summary="Global feature importances from active model",
    dependencies=[Depends(require_admin_token)],
)
async def get_feature_importance(
    db: AsyncSession = Depends(get_db),
):
    """Get global feature importances from the active ML model."""
    from app.domain.services.ml_risk_model import RiskMLModel
    from app.infrastructure.db.repositories.ml_model_repository import MLModelRepository

    repo = MLModelRepository(db)
    artifact = await repo.get_active_model("risk_scoring_v1")
    if not artifact:
        return {
            "status": "ok",
            "data": {
                "message": "No active ML model. Train a model first.",
                "importances": None,
            },
        }

    model = RiskMLModel.deserialize(artifact.model_binary)
    importances = dict(
        zip(model.feature_names, model.clf.feature_importances_.tolist())
    )

    # Sort by importance descending
    sorted_importances = dict(
        sorted(importances.items(), key=lambda x: x[1], reverse=True)
    )

    return {
        "status": "ok",
        "data": {
            "model_version": artifact.version,
            "importances": {k: round(v, 6) for k, v in sorted_importances.items()},
        },
    }


@router.get(
    "/cold-start",
    summary="Training data availability check",
    dependencies=[Depends(require_admin_token)],
)
async def cold_start_check(
    db: AsyncSession = Depends(get_db),
):
    """Check how much labeled training data is available."""
    from app.domain.services.ml_training_pipeline import check_cold_start

    result = await check_cold_start(db)
    return {"status": "ok", "data": result}
