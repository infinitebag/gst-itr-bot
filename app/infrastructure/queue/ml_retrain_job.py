# app/infrastructure/queue/ml_retrain_job.py
"""
ARQ job for periodic ML model retraining.

Checks if enough new CA-labeled outcomes have accumulated since the last
model was trained, and triggers a retrain if so.  Runs as a weekly cron.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings

logger = logging.getLogger("ml_retrain_job")


async def ml_retrain_job(ctx: dict) -> dict:
    """Auto-retrain ML risk model if enough new labels exist.

    Steps:
    1. Check cold-start readiness
    2. Count new labels since last model trained_at
    3. If above threshold, train and store
    4. Return status dict
    """
    from app.core.db import AsyncSessionLocal
    from app.domain.services.ml_training_pipeline import (
        check_cold_start,
        train_and_store,
    )
    from app.infrastructure.db.repositories.ml_model_repository import MLModelRepository

    async with AsyncSessionLocal() as db:
        # 1. Cold-start check
        cold_start = await check_cold_start(db)
        if not cold_start["ready"]:
            logger.info(
                "ML retrain: cold start — %d/%d samples, skipping",
                cold_start["labeled_count"],
                cold_start["min_required"],
            )
            return {
                "action": "skipped",
                "reason": "cold_start",
                "labeled_count": cold_start["labeled_count"],
                "min_required": cold_start["min_required"],
            }

        # 2. Check new labels since last model
        repo = MLModelRepository(db)
        active_model = await repo.get_active_model("risk_scoring_v1")

        if active_model:
            new_labels = await repo.count_new_labels_since(active_model.trained_at)
            if new_labels < settings.ML_RISK_RETRAIN_THRESHOLD:
                logger.info(
                    "ML retrain: only %d new labels since v%d "
                    "(need %d), skipping",
                    new_labels, active_model.version,
                    settings.ML_RISK_RETRAIN_THRESHOLD,
                )
                return {
                    "action": "skipped",
                    "reason": "below_threshold",
                    "new_labels": new_labels,
                    "threshold": settings.ML_RISK_RETRAIN_THRESHOLD,
                    "active_version": active_model.version,
                }

        # 3. Train
        try:
            result = await train_and_store(db, auto_activate=True)
            logger.info(
                "ML retrain complete: v%d, accuracy=%.4f, f1=%.4f, activated=%s",
                result.version, result.accuracy, result.f1_macro,
                result.auto_activated,
            )
            return {
                "action": "trained",
                "version": result.version,
                "accuracy": result.accuracy,
                "f1_macro": result.f1_macro,
                "training_samples": result.training_samples,
                "auto_activated": result.auto_activated,
            }
        except ValueError as exc:
            logger.warning("ML retrain failed: %s", exc)
            return {"action": "failed", "error": str(exc)}
        except Exception:
            logger.exception("ML retrain unexpected error")
            return {"action": "failed", "error": "unexpected_error"}
