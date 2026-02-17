# app/domain/services/ml_feature_engineering.py
"""
Feature engineering for ML-powered risk scoring.

Converts the existing RiskMetrics dataclass into a numeric feature vector
suitable for scikit-learn models.  30 features total:
  24 base features from RiskMetrics fields
  6 derived features (ratios, slopes, one-hot flags)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

logger = logging.getLogger("ml_feature_engineering")

# ── Feature names (order matters — must match training) ────────

FEATURE_NAMES: list[str] = [
    # Base features (24) — direct from RiskMetrics
    "total_outward_invoices",
    "total_inward_invoices",
    "duplicate_invoice_count",
    "missing_gstin_b2b_count",
    "pos_mismatch_count",
    "amendment_count",
    "has_2b_data",
    "total_2b_entries",
    "matched_count",
    "missing_in_2b_count",
    "value_mismatch_count",
    "missing_in_books_count",
    "itc_claimed",
    "output_tax_total",
    "blocked_itc_count",
    "itc_ratio",
    "rcm_total",
    "net_payable",
    "total_paid",
    "payment_count",
    "days_past_due",
    "avg_turnover_3",
    "avg_itc_3",
    "current_turnover",
    # Derived features (6)
    "amendment_trend_slope",
    "is_composition",
    "is_qrmp",
    "payment_coverage_ratio",
    "itc_2b_match_ratio",
    "outward_inward_ratio",
]

FEATURE_COUNT: int = len(FEATURE_NAMES)  # 30


@dataclass
class FeatureVector:
    """Typed wrapper around a numpy feature vector."""

    values: np.ndarray          # shape (FEATURE_COUNT,)
    feature_names: list[str]    # same order as values

    def to_dict(self) -> dict[str, float]:
        """Return feature name → value mapping."""
        return {n: float(v) for n, v in zip(self.feature_names, self.values)}


def _to_float(val) -> float:
    """Safely convert Decimal / None / int to float."""
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def _compute_amendment_trend_slope(trend: list[int]) -> float:
    """Linear regression slope of amendment counts over last 3 periods.

    If fewer than 2 data points, returns 0.0.
    """
    if not trend or len(trend) < 2:
        return 0.0
    n = len(trend)
    x = np.arange(n, dtype=float)
    y = np.array(trend, dtype=float)
    # slope = Σ((xi - x̄)(yi - ȳ)) / Σ((xi - x̄)²)
    x_mean = x.mean()
    y_mean = y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0:
        return 0.0
    return float(((x - x_mean) * (y - y_mean)).sum() / denom)


def metrics_to_features(metrics) -> FeatureVector:
    """Convert a RiskMetrics dataclass to a 30-element feature vector.

    Parameters
    ----------
    metrics : RiskMetrics
        The risk metrics loaded from DB for a return period.

    Returns
    -------
    FeatureVector
        Numpy array of shape (30,) with named features.
    """
    # Base features (24)
    base = [
        float(metrics.total_outward_invoices),
        float(metrics.total_inward_invoices),
        float(metrics.duplicate_invoice_count),
        float(metrics.missing_gstin_b2b_count),
        float(metrics.pos_mismatch_count),
        float(metrics.amendment_count),
        1.0 if metrics.has_2b_data else 0.0,
        float(metrics.total_2b_entries),
        float(metrics.matched_count),
        float(metrics.missing_in_2b_count),
        float(metrics.value_mismatch_count),
        float(metrics.missing_in_books_count),
        _to_float(metrics.itc_claimed),
        _to_float(metrics.output_tax_total),
        float(metrics.blocked_itc_count),
        float(metrics.itc_ratio),
        _to_float(metrics.rcm_total),
        _to_float(metrics.net_payable),
        _to_float(metrics.total_paid),
        float(metrics.payment_count),
        float(metrics.days_past_due),
        _to_float(metrics.avg_turnover_3),
        _to_float(metrics.avg_itc_3),
        _to_float(metrics.current_turnover),
    ]

    # Derived features (6)
    amendment_trend_slope = _compute_amendment_trend_slope(
        getattr(metrics, "amendment_trend", [])
    )

    is_composition = 1.0 if getattr(metrics, "taxpayer_type", "regular") == "composition" else 0.0
    is_qrmp = 1.0 if getattr(metrics, "taxpayer_type", "regular") == "qrmp" else 0.0

    net_pay = _to_float(metrics.net_payable)
    total_paid_f = _to_float(metrics.total_paid)
    payment_coverage_ratio = (total_paid_f / net_pay) if net_pay > 0 else 1.0

    total_2b = max(float(metrics.total_2b_entries), 1.0)
    itc_2b_match_ratio = float(metrics.matched_count) / total_2b

    inward = max(float(metrics.total_inward_invoices), 1.0)
    outward_inward_ratio = float(metrics.total_outward_invoices) / inward

    derived = [
        amendment_trend_slope,
        is_composition,
        is_qrmp,
        payment_coverage_ratio,
        itc_2b_match_ratio,
        outward_inward_ratio,
    ]

    values = np.array(base + derived, dtype=np.float64)

    # Replace NaN / inf with 0
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)

    return FeatureVector(values=values, feature_names=list(FEATURE_NAMES))
