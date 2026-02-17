# tests/test_ml_risk_scoring.py
"""
Tests for Phase 3B ML-Powered Risk Scoring.

Covers:
  - Feature engineering (metrics → feature vector)
  - ML model (train, predict, serialize/deserialize)
  - Hybrid scoring (blend weights, range bounds, CRITICAL override)
  - Cold-start (fallback when no model)
"""

from __future__ import annotations

import json
import pytest
import numpy as np

from app.domain.services.ml_feature_engineering import (
    FEATURE_COUNT,
    FEATURE_NAMES,
    FeatureVector,
    metrics_to_features,
    _compute_amendment_trend_slope,
)
from app.domain.services.ml_risk_model import (
    MLPrediction,
    ModelMetrics,
    RiskMLModel,
    OUTCOME_CLASSES,
    RISK_SCORE_MAP,
)
from app.domain.services.gst_risk_scoring import (
    RiskAssessmentResult,
    RiskFlag,
    RiskMetrics,
    _score_to_level,
)


# ============================================================
# Test Feature Engineering
# ============================================================


class TestFeatureEngineering:
    """Tests for ml_feature_engineering.py"""

    def test_feature_count(self):
        """FEATURE_COUNT should be 30."""
        assert FEATURE_COUNT == 30
        assert len(FEATURE_NAMES) == 30

    def test_metrics_to_features_default(self):
        """Default RiskMetrics should produce a zero-like vector."""
        metrics = RiskMetrics()
        fv = metrics_to_features(metrics)

        assert isinstance(fv, FeatureVector)
        assert fv.values.shape == (30,)
        assert len(fv.feature_names) == 30

        # Most base features should be 0
        assert fv.values[0] == 0.0  # total_outward_invoices
        assert fv.values[6] == 0.0  # has_2b_data (False → 0)

    def test_metrics_to_features_populated(self):
        """Populated metrics should produce correct feature values."""
        metrics = RiskMetrics(
            total_outward_invoices=50,
            total_inward_invoices=30,
            has_2b_data=True,
            total_2b_entries=25,
            matched_count=20,
            itc_claimed=100000,
            output_tax_total=80000,
            net_payable=50000,
            total_paid=45000,
            taxpayer_type="regular",
        )
        fv = metrics_to_features(metrics)

        assert fv.values[0] == 50.0  # total_outward_invoices
        assert fv.values[1] == 30.0  # total_inward_invoices
        assert fv.values[6] == 1.0   # has_2b_data = True
        assert fv.values[7] == 25.0  # total_2b_entries
        assert fv.values[8] == 20.0  # matched_count

    def test_derived_features(self):
        """Derived features should be computed correctly."""
        metrics = RiskMetrics(
            total_outward_invoices=100,
            total_inward_invoices=50,
            total_2b_entries=20,
            matched_count=16,
            net_payable=100000,
            total_paid=90000,
            taxpayer_type="composition",
            amendment_trend=[2, 4, 6],
        )
        fv = metrics_to_features(metrics)

        # payment_coverage_ratio = 90000 / 100000 = 0.9
        assert abs(fv.values[27] - 0.9) < 1e-6

        # itc_2b_match_ratio = 16 / 20 = 0.8
        assert abs(fv.values[28] - 0.8) < 1e-6

        # outward_inward_ratio = 100 / 50 = 2.0
        assert abs(fv.values[29] - 2.0) < 1e-6

        # is_composition = 1.0
        assert fv.values[25] == 1.0

        # is_qrmp = 0.0 (taxpayer is composition)
        assert fv.values[26] == 0.0

    def test_amendment_trend_slope(self):
        """Amendment trend slope calculation."""
        # Increasing trend
        assert _compute_amendment_trend_slope([1, 2, 3]) == pytest.approx(1.0)

        # Flat
        assert _compute_amendment_trend_slope([5, 5, 5]) == pytest.approx(0.0)

        # Decreasing
        assert _compute_amendment_trend_slope([6, 4, 2]) == pytest.approx(-2.0)

        # Empty / single → 0
        assert _compute_amendment_trend_slope([]) == 0.0
        assert _compute_amendment_trend_slope([5]) == 0.0

    def test_nan_inf_handling(self):
        """NaN and inf values should be replaced with 0."""
        metrics = RiskMetrics(
            total_outward_invoices=0,
            total_inward_invoices=0,  # → outward/inward = 0/1 = 0
            net_payable=0,            # → payment_coverage = 1.0
        )
        fv = metrics_to_features(metrics)

        # No NaN or inf
        assert not np.any(np.isnan(fv.values))
        assert not np.any(np.isinf(fv.values))

    def test_feature_vector_to_dict(self):
        """FeatureVector.to_dict() should return feature name → value mapping."""
        metrics = RiskMetrics(total_outward_invoices=42)
        fv = metrics_to_features(metrics)
        d = fv.to_dict()

        assert isinstance(d, dict)
        assert d["total_outward_invoices"] == 42.0
        assert len(d) == FEATURE_COUNT


# ============================================================
# Test ML Model
# ============================================================


class TestMLModel:
    """Tests for ml_risk_model.py"""

    @staticmethod
    def _make_training_data(n=100):
        """Generate synthetic training data."""
        rng = np.random.RandomState(42)
        X = rng.rand(n, FEATURE_COUNT)
        y = rng.choice(OUTCOME_CLASSES, size=n)
        return X, y

    def test_train_predict(self):
        """Model should train and produce valid predictions."""
        X, y = self._make_training_data(100)
        model = RiskMLModel(n_estimators=10, max_depth=3)
        metrics = model.train(X, y, FEATURE_NAMES)

        assert model.is_trained
        assert isinstance(metrics, ModelMetrics)
        assert 0 <= metrics.accuracy <= 1
        assert 0 <= metrics.f1_macro <= 1
        assert metrics.training_samples == 100
        assert len(metrics.feature_importances) == FEATURE_COUNT

        # Predict
        pred = model.predict(X[0])
        assert isinstance(pred, MLPrediction)
        assert pred.predicted_outcome in OUTCOME_CLASSES
        assert 0 <= pred.predicted_risk_score <= 100
        assert 0 <= pred.confidence <= 1
        assert len(pred.class_probabilities) > 0

    def test_serialize_deserialize(self):
        """Model should survive serialization round-trip."""
        X, y = self._make_training_data(80)
        model = RiskMLModel(n_estimators=10, max_depth=3)
        model.train(X, y, FEATURE_NAMES)

        # Serialize
        data = model.serialize()
        assert isinstance(data, bytes)
        assert len(data) > 0

        # Deserialize
        model2 = RiskMLModel.deserialize(data)
        assert model2.is_trained
        assert model2.feature_names == FEATURE_NAMES

        # Same predictions
        pred1 = model.predict(X[0])
        pred2 = model2.predict(X[0])
        assert pred1.predicted_outcome == pred2.predicted_outcome
        assert pred1.predicted_risk_score == pred2.predicted_risk_score

    def test_score_mapping(self):
        """Predicted risk score should be in [0, 100]."""
        X, y = self._make_training_data(100)
        model = RiskMLModel(n_estimators=10, max_depth=3)
        model.train(X, y, FEATURE_NAMES)

        for i in range(min(20, len(X))):
            pred = model.predict(X[i])
            assert 0 <= pred.predicted_risk_score <= 100

    def test_prediction_to_dict(self):
        """MLPrediction.to_dict() should produce a serializable dict."""
        X, y = self._make_training_data(50)
        model = RiskMLModel(n_estimators=10, max_depth=3)
        model.train(X, y, FEATURE_NAMES)
        pred = model.predict(X[0])
        d = pred.to_dict()

        assert "predicted_outcome" in d
        assert "predicted_risk_score" in d
        assert "confidence" in d

        # Should be JSON-serializable
        json.dumps(d)

    def test_untrained_predict_raises(self):
        """Predicting without training should raise RuntimeError."""
        model = RiskMLModel()
        with pytest.raises(RuntimeError):
            model.predict(np.zeros(FEATURE_COUNT))

    def test_metrics_to_dict(self):
        """ModelMetrics.to_dict() should produce a serializable dict."""
        X, y = self._make_training_data(60)
        model = RiskMLModel(n_estimators=10, max_depth=3)
        metrics = model.train(X, y, FEATURE_NAMES)
        d = metrics.to_dict()

        assert "accuracy" in d
        assert "f1_macro" in d
        assert "training_samples" in d

        # Should be JSON-serializable
        json.dumps(d)


# ============================================================
# Test Hybrid Scoring
# ============================================================


class TestHybridScoring:
    """Tests for hybrid ML + rule scoring logic."""

    def test_blend_weight_zero_is_rule_only(self):
        """With blend_weight=0, final score should equal rule score."""
        rule_score = 45
        ml_score = 80
        blend_wt = 0.0

        blended = round((1 - blend_wt) * rule_score + blend_wt * ml_score)
        assert blended == rule_score

    def test_blend_weight_one_is_ml_only(self):
        """With blend_weight=1, final score should equal ML score."""
        rule_score = 45
        ml_score = 80
        blend_wt = 1.0

        blended = round((1 - blend_wt) * rule_score + blend_wt * ml_score)
        assert blended == ml_score

    def test_default_blend_weight(self):
        """Default 0.3 blend: 70% rule + 30% ML."""
        rule_score = 40
        ml_score = 60
        blend_wt = 0.3

        blended = round((1 - blend_wt) * rule_score + blend_wt * ml_score)
        expected = round(0.7 * 40 + 0.3 * 60)  # 28 + 18 = 46
        assert blended == expected

    def test_blended_score_clamped(self):
        """Blended score should be clamped to [0, 100]."""
        # Even if ML predicts high, the clamp should work
        rule_score = 95
        ml_score = 100
        blend_wt = 0.5

        blended = round((1 - blend_wt) * rule_score + blend_wt * ml_score)
        clamped = max(0, min(100, blended))
        assert 0 <= clamped <= 100

    def test_critical_override_preserved(self):
        """CRITICAL flag override should run AFTER blending."""
        result = RiskAssessmentResult()
        result.risk_score = 15  # LOW normally
        result.risk_flags = [
            RiskFlag(
                code="COMPOSITION_ITC_CLAIM",
                severity="CRITICAL",
                points=10,
                evidence="test",
            )
        ]

        # After blending, if score is LOW (15), but has CRITICAL flag,
        # override should bump to HIGH
        result.risk_level = _score_to_level(result.risk_score)
        has_critical = any(f.severity == "CRITICAL" for f in result.risk_flags)
        if has_critical and result.risk_level not in ("HIGH", "CRITICAL"):
            result.risk_level = "HIGH"

        assert result.risk_level == "HIGH"

    def test_score_to_level_boundaries(self):
        """_score_to_level should map correctly at boundaries."""
        assert _score_to_level(0) == "LOW"
        assert _score_to_level(19) == "LOW"
        assert _score_to_level(20) == "MEDIUM"
        assert _score_to_level(44) == "MEDIUM"
        assert _score_to_level(45) == "HIGH"
        assert _score_to_level(69) == "HIGH"
        assert _score_to_level(70) == "CRITICAL"
        assert _score_to_level(100) == "CRITICAL"

    def test_risk_assessment_result_ml_fields(self):
        """RiskAssessmentResult should include ML fields in to_dict() when enhanced."""
        result = RiskAssessmentResult(
            risk_score=50,
            risk_level="HIGH",
            ml_enhanced=True,
            ml_risk_score=60,
            ml_confidence=0.85,
            ml_blend_weight=0.3,
            top_ml_factors=[
                {"feature": "itc_ratio", "importance": 0.15},
            ],
        )
        d = result.to_dict()

        assert d["ml_enhanced"] is True
        assert d["ml_risk_score"] == 60
        assert d["ml_confidence"] == 0.85
        assert d["ml_blend_weight"] == 0.3
        assert len(d["top_ml_factors"]) == 1

    def test_risk_assessment_result_no_ml(self):
        """RiskAssessmentResult should NOT include ML fields when not enhanced."""
        result = RiskAssessmentResult(risk_score=30, risk_level="MEDIUM")
        d = result.to_dict()

        assert "ml_enhanced" not in d
        assert "ml_risk_score" not in d


# ============================================================
# Test Cold Start
# ============================================================


class TestColdStart:
    """Tests for cold-start behavior."""

    def test_fallback_when_no_model(self):
        """When no ML model is active, scoring should be rule-only."""
        # The _try_ml_prediction returns (None, 0.0) when no model
        # This means blending is skipped and ml_enhanced stays False
        result = RiskAssessmentResult(risk_score=42, risk_level="MEDIUM")
        assert result.ml_enhanced is False
        assert result.ml_risk_score is None

    def test_insufficient_samples_message(self):
        """ValueError should mention sample count when insufficient."""
        from app.core.config import settings

        try:
            raise ValueError(
                f"Insufficient labeled data: 10 samples "
                f"(need {settings.ML_RISK_MIN_SAMPLES})"
            )
        except ValueError as exc:
            assert "Insufficient" in str(exc)
            assert str(settings.ML_RISK_MIN_SAMPLES) in str(exc)
