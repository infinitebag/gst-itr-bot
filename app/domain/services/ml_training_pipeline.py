# app/domain/services/ml_training_pipeline.py
"""
Training pipeline for the ML risk scoring model.

Collects CA-labeled RiskAssessment records, extracts features, trains
a GradientBoosting model, stores the serialized model in PostgreSQL,
and optionally auto-activates if quality exceeds the previous active model.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infrastructure.db.models import RiskAssessment, ReturnPeriod

logger = logging.getLogger("ml_training_pipeline")

MODEL_NAME = "risk_scoring_v1"


@dataclass
class TrainingResult:
    """Outcome of a training run."""
    model_id: str
    version: int
    training_samples: int
    accuracy: float
    f1_macro: float
    feature_importances: dict[str, float]
    auto_activated: bool

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "training_samples": self.training_samples,
            "accuracy": round(self.accuracy, 4),
            "f1_macro": round(self.f1_macro, 4),
            "feature_importances": {
                k: round(v, 6) for k, v in self.feature_importances.items()
            },
            "auto_activated": self.auto_activated,
        }


async def collect_training_data(
    db: AsyncSession,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Collect labeled training data from CA-reviewed risk assessments.

    Returns
    -------
    X : np.ndarray  shape (n_samples, 30)
    y : np.ndarray  shape (n_samples,) — string labels
    feature_names : list[str]
    """
    from app.domain.services.gst_risk_scoring import _load_risk_metrics
    from app.domain.services.ml_feature_engineering import (
        metrics_to_features,
        FEATURE_NAMES,
    )

    # Query all risk assessments with CA outcomes
    stmt = (
        select(RiskAssessment)
        .where(RiskAssessment.ca_final_outcome.is_not(None))
        .order_by(RiskAssessment.computed_at.desc())
    )
    result = await db.execute(stmt)
    assessments = list(result.scalars().all())

    if not assessments:
        return np.empty((0, len(FEATURE_NAMES))), np.empty(0), FEATURE_NAMES

    X_list = []
    y_list = []

    for ra in assessments:
        try:
            metrics = await _load_risk_metrics(ra.period_id, db)
            fv = metrics_to_features(metrics)
            X_list.append(fv.values)
            y_list.append(ra.ca_final_outcome)
        except Exception:
            logger.warning(
                "Failed to extract features for assessment %s (period %s)",
                ra.id, ra.period_id, exc_info=True,
            )
            continue

    if not X_list:
        return np.empty((0, len(FEATURE_NAMES))), np.empty(0), FEATURE_NAMES

    X = np.vstack(X_list)
    y = np.array(y_list)
    return X, y, FEATURE_NAMES


async def check_cold_start(db: AsyncSession) -> dict:
    """Check if we have enough labeled data to train.

    Returns
    -------
    dict with keys: labeled_count, min_required, ready, by_outcome
    """
    # Total labeled
    total_stmt = (
        select(func.count(RiskAssessment.id))
        .where(RiskAssessment.ca_final_outcome.is_not(None))
    )
    total_result = await db.execute(total_stmt)
    labeled_count = total_result.scalar_one() or 0

    # Breakdown by outcome
    breakdown_stmt = (
        select(
            RiskAssessment.ca_final_outcome,
            func.count(RiskAssessment.id).label("cnt"),
        )
        .where(RiskAssessment.ca_final_outcome.is_not(None))
        .group_by(RiskAssessment.ca_final_outcome)
    )
    breakdown_result = await db.execute(breakdown_stmt)
    by_outcome = {row[0]: row[1] for row in breakdown_result.all()}

    return {
        "labeled_count": labeled_count,
        "min_required": settings.ML_RISK_MIN_SAMPLES,
        "ready": labeled_count >= settings.ML_RISK_MIN_SAMPLES,
        "by_outcome": by_outcome,
    }


async def train_and_store(
    db: AsyncSession,
    auto_activate: bool = True,
) -> TrainingResult:
    """Full training pipeline: collect → train → store → optionally activate.

    Raises
    ------
    ValueError if insufficient labeled data.
    """
    from app.domain.services.ml_risk_model import RiskMLModel
    from app.infrastructure.db.repositories.ml_model_repository import MLModelRepository

    # 1. Collect training data
    X, y, feature_names = await collect_training_data(db)

    if len(y) < settings.ML_RISK_MIN_SAMPLES:
        raise ValueError(
            f"Insufficient labeled data: {len(y)} samples "
            f"(need {settings.ML_RISK_MIN_SAMPLES}). "
            f"CAs need to review more assessments."
        )

    # 2. Train model
    model = RiskMLModel(
        n_estimators=settings.ML_RISK_N_ESTIMATORS,
        max_depth=settings.ML_RISK_MAX_DEPTH,
    )

    repo = MLModelRepository(db)

    # Determine version
    existing = await repo.list_models(MODEL_NAME, limit=1)
    next_version = (existing[0].version + 1) if existing else 1

    metrics = model.train(
        X, y, feature_names, model_version=next_version,
    )

    # 3. Serialize
    model_binary = model.serialize()

    # 4. Store
    artifact = await repo.store_model(
        model_name=MODEL_NAME,
        model_binary=model_binary,
        training_samples=metrics.training_samples,
        accuracy=metrics.accuracy,
        f1_macro=metrics.f1_macro,
        metrics_json=json.dumps(metrics.to_dict()),
        feature_names_json=json.dumps(feature_names),
    )

    # 5. Auto-activate if quality exceeds previous
    activated = False
    if auto_activate:
        current_active = await repo.get_active_model(MODEL_NAME)
        should_activate = True

        if current_active and current_active.f1_macro is not None:
            # Only activate if F1 is equal or better
            if metrics.f1_macro < current_active.f1_macro:
                should_activate = False
                logger.info(
                    "New model v%d F1=%.4f < active v%d F1=%.4f — "
                    "not auto-activating",
                    artifact.version, metrics.f1_macro,
                    current_active.version, current_active.f1_macro,
                )

        if should_activate:
            await repo.activate_model(artifact.id)
            activated = True
            logger.info(
                "Auto-activated model v%d (F1=%.4f, accuracy=%.4f, samples=%d)",
                artifact.version, metrics.f1_macro, metrics.accuracy,
                metrics.training_samples,
            )

    result = TrainingResult(
        model_id=str(artifact.id),
        version=artifact.version,
        training_samples=metrics.training_samples,
        accuracy=metrics.accuracy,
        f1_macro=metrics.f1_macro,
        feature_importances=metrics.feature_importances,
        auto_activated=activated,
    )

    logger.info("Training complete: %s", result.to_dict())
    return result
