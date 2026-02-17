# app/domain/services/ml_risk_model.py
"""
scikit-learn GradientBoosting model for GST risk prediction.

Trained on CA-labeled RiskAssessment records.  Three target classes:
  "approved"               → risk score 10
  "approved_with_changes"  → risk score 45
  "major_changes"          → risk score 80

The predicted risk score is a probability-weighted sum:
  score = Σ( P(class) × risk_map[class] )

SHAP values provide per-prediction explainability.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

logger = logging.getLogger("ml_risk_model")

# ── Target class → risk score mapping ─────────────────────────

OUTCOME_CLASSES = ["approved", "approved_with_changes", "major_changes"]
RISK_SCORE_MAP = {
    "approved": 10,
    "approved_with_changes": 45,
    "major_changes": 80,
}


# ── Data classes ──────────────────────────────────────────────

@dataclass
class MLPrediction:
    """Result of a single prediction."""
    predicted_outcome: str                             # "approved", etc.
    predicted_risk_score: int                          # 0-100
    class_probabilities: dict[str, float]              # {class: probability}
    feature_importances: dict[str, float] | None       # global importances
    shap_values: dict[str, float] | None               # per-prediction SHAP
    confidence: float                                  # max probability

    def to_dict(self) -> dict:
        return {
            "predicted_outcome": self.predicted_outcome,
            "predicted_risk_score": self.predicted_risk_score,
            "class_probabilities": self.class_probabilities,
            "feature_importances": self.feature_importances,
            "shap_values": self.shap_values,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class ModelMetrics:
    """Training evaluation metrics."""
    accuracy: float
    f1_macro: float
    classification_report_dict: dict
    confusion_matrix_list: list[list[int]]
    feature_importances: dict[str, float]
    training_samples: int
    model_version: int = 0

    def to_dict(self) -> dict:
        return {
            "accuracy": round(self.accuracy, 4),
            "f1_macro": round(self.f1_macro, 4),
            "classification_report": self.classification_report_dict,
            "confusion_matrix": self.confusion_matrix_list,
            "feature_importances": {
                k: round(v, 6) for k, v in self.feature_importances.items()
            },
            "training_samples": self.training_samples,
            "model_version": self.model_version,
        }


# ── Model class ───────────────────────────────────────────────

class RiskMLModel:
    """GradientBoosting classifier for GST risk scoring."""

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
    ) -> None:
        self.clf = GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=42,
            subsample=0.8,
            learning_rate=0.1,
        )
        self.feature_names: list[str] = []
        self._is_trained: bool = False

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        test_size: float = 0.2,
        model_version: int = 0,
    ) -> ModelMetrics:
        """Train the model on labeled data with stratified train/test split.

        Parameters
        ----------
        X : np.ndarray  shape (n_samples, n_features)
        y : np.ndarray  shape (n_samples,) — string labels
        feature_names : list[str]
        test_size : float
        model_version : int

        Returns
        -------
        ModelMetrics with evaluation on the test split.
        """
        self.feature_names = feature_names

        # Stratified split
        if len(set(y)) < 2 or len(y) < 10:
            # Not enough diversity — train on all, report on all
            X_train, X_test, y_train, y_test = X, X, y, y
            logger.warning(
                "Insufficient class diversity (%d classes, %d samples) — "
                "training on all data without split",
                len(set(y)), len(y),
            )
        else:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, stratify=y, random_state=42,
            )

        self.clf.fit(X_train, y_train)
        self._is_trained = True

        # Evaluate
        y_pred = self.clf.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred, average="macro", zero_division=0)
        report = classification_report(
            y_test, y_pred, output_dict=True, zero_division=0,
        )
        cm = confusion_matrix(y_test, y_pred, labels=self.clf.classes_).tolist()

        # Feature importances
        importances = dict(
            zip(feature_names, self.clf.feature_importances_.tolist())
        )

        logger.info(
            "Model trained: accuracy=%.4f, f1_macro=%.4f, samples=%d",
            acc, f1, len(y),
        )

        return ModelMetrics(
            accuracy=acc,
            f1_macro=f1,
            classification_report_dict=report,
            confusion_matrix_list=cm,
            feature_importances=importances,
            training_samples=len(y),
            model_version=model_version,
        )

    def predict(
        self,
        features: np.ndarray,
        compute_shap: bool = False,
    ) -> MLPrediction:
        """Predict risk for a single feature vector.

        Parameters
        ----------
        features : np.ndarray  shape (n_features,)
        compute_shap : bool  — whether to compute SHAP values

        Returns
        -------
        MLPrediction
        """
        if not self._is_trained:
            raise RuntimeError("Model not trained — call train() or deserialize() first")

        X = features.reshape(1, -1)
        probabilities = self.clf.predict_proba(X)[0]
        classes = self.clf.classes_.tolist()

        # Build class → probability map
        class_probs = dict(zip(classes, [round(float(p), 4) for p in probabilities]))

        # Predicted outcome = highest probability class
        predicted_class = classes[int(np.argmax(probabilities))]

        # Probability-weighted risk score
        risk_score = sum(
            float(p) * RISK_SCORE_MAP.get(cls, 50)
            for cls, p in zip(classes, probabilities)
        )
        risk_score = max(0, min(100, round(risk_score)))

        # Confidence
        confidence = float(np.max(probabilities))

        # Feature importances (global — from training)
        importances = None
        if self.feature_names:
            importances = dict(
                zip(self.feature_names, self.clf.feature_importances_.tolist())
            )

        # SHAP
        shap_values = None
        if compute_shap:
            shap_values = self._compute_shap(X)

        return MLPrediction(
            predicted_outcome=predicted_class,
            predicted_risk_score=risk_score,
            class_probabilities=class_probs,
            feature_importances=importances,
            shap_values=shap_values,
            confidence=confidence,
        )

    def _compute_shap(self, X: np.ndarray) -> dict[str, float] | None:
        """Compute SHAP values for a single prediction."""
        try:
            import shap

            explainer = shap.TreeExplainer(self.clf)
            shap_vals = explainer.shap_values(X)

            # For multi-class, shap_vals is a list of arrays (one per class).
            # We pick the predicted class's SHAP values.
            pred_idx = int(np.argmax(self.clf.predict_proba(X)[0]))

            if isinstance(shap_vals, list):
                vals = shap_vals[pred_idx][0]
            else:
                vals = shap_vals[0]

            return dict(
                zip(self.feature_names, [round(float(v), 6) for v in vals])
            )
        except Exception:
            logger.warning("SHAP computation failed", exc_info=True)
            return None

    # ── Serialization ─────────────────────────────────────────

    def serialize(self) -> bytes:
        """Serialize model + metadata to bytes via joblib."""
        buf = io.BytesIO()
        data = {
            "clf": self.clf,
            "feature_names": self.feature_names,
            "is_trained": self._is_trained,
            "serialized_at": datetime.now(timezone.utc).isoformat(),
        }
        joblib.dump(data, buf, compress=3)
        return buf.getvalue()

    @classmethod
    def deserialize(cls, data: bytes) -> RiskMLModel:
        """Reconstruct model from serialized bytes."""
        buf = io.BytesIO(data)
        loaded = joblib.load(buf)

        model = cls.__new__(cls)
        model.clf = loaded["clf"]
        model.feature_names = loaded["feature_names"]
        model._is_trained = loaded.get("is_trained", True)
        return model
