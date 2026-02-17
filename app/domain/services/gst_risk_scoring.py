# app/domain/services/gst_risk_scoring.py
"""
100-point Risk Scoring Engine for GST return periods.

Categories:
  A — Data Quality (max 20)
  B — ITC & 2B Reconciliation (max 35)
  C — Liability / Payment / Filing (max 20)
  D — Behavioral / Anomaly (max 15)
  E — Policy / Structural (max 10)

Thresholds:  0-19 LOW | 20-44 MEDIUM | 45-69 HIGH | 70-100 CRITICAL
Override:    Any single CRITICAL flag → level at least HIGH.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    Invoice,
    ITCMatch,
    PaymentRecord,
    ReturnPeriod,
    BusinessClient,
)

logger = logging.getLogger("gst_risk_scoring")

# ──────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────

@dataclass
class RiskFlag:
    code: str
    severity: str  # LOW / MEDIUM / HIGH / CRITICAL
    points: int
    evidence: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "points": self.points,
            "evidence": self.evidence,
        }


@dataclass
class RecommendedAction:
    action: str
    why: str

    def to_dict(self) -> dict:
        return {"action": self.action, "why": self.why}


@dataclass
class RiskMetrics:
    """All inputs needed for risk scoring, loaded once from DB."""
    # Invoice-level
    total_outward_invoices: int = 0
    total_inward_invoices: int = 0
    duplicate_invoice_count: int = 0
    missing_gstin_b2b_count: int = 0
    pos_mismatch_count: int = 0
    amendment_count: int = 0

    # 2B reconciliation
    has_2b_data: bool = False
    total_2b_entries: int = 0
    matched_count: int = 0
    missing_in_2b_count: int = 0
    value_mismatch_count: int = 0
    missing_in_books_count: int = 0

    # ITC
    itc_claimed: Decimal = Decimal("0")
    output_tax_total: Decimal = Decimal("0")
    blocked_itc_count: int = 0
    itc_ratio: float = 0.0

    # RCM
    rcm_total: Decimal = Decimal("0")

    # Payment
    net_payable: Decimal = Decimal("0")
    total_paid: Decimal = Decimal("0")
    payment_count: int = 0

    # Filing
    due_date_gstr3b: date | None = None
    period_status: str = "draft"
    days_past_due: int = 0

    # Historical (last 3 periods)
    avg_turnover_3: Decimal = Decimal("0")
    avg_itc_3: Decimal = Decimal("0")
    current_turnover: Decimal = Decimal("0")
    amendment_trend: list[int] = field(default_factory=list)

    # Taxpayer type
    taxpayer_type: str = "regular"
    filing_mode: str = "monthly"


@dataclass
class RiskAssessmentResult:
    """Output from compute_risk_score()."""
    risk_score: int = 0
    risk_level: str = "LOW"
    risk_flags: list[RiskFlag] = field(default_factory=list)
    recommended_actions: list[RecommendedAction] = field(default_factory=list)
    category_a_score: int = 0  # Data Quality
    category_b_score: int = 0  # ITC & 2B
    category_c_score: int = 0  # Liability/Payment/Filing
    category_d_score: int = 0  # Behavioral/Anomaly
    category_e_score: int = 0  # Policy/Structural

    # ML scoring (Phase 3B) — populated when an active ML model exists
    ml_risk_score: int | None = None
    ml_enhanced: bool = False
    ml_confidence: float | None = None
    ml_blend_weight: float = 0.0
    ml_prediction_json: str | None = None
    top_ml_factors: list[dict] | None = None

    def to_dict(self) -> dict:
        d = {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "risk_flags": [f.to_dict() for f in self.risk_flags],
            "recommended_actions": [a.to_dict() for a in self.recommended_actions],
            "category_a_score": self.category_a_score,
            "category_b_score": self.category_b_score,
            "category_c_score": self.category_c_score,
            "category_d_score": self.category_d_score,
            "category_e_score": self.category_e_score,
        }
        # ML fields (only included when ML model was used)
        if self.ml_enhanced:
            d["ml_risk_score"] = self.ml_risk_score
            d["ml_enhanced"] = self.ml_enhanced
            d["ml_confidence"] = self.ml_confidence
            d["ml_blend_weight"] = self.ml_blend_weight
            if self.top_ml_factors:
                d["top_ml_factors"] = self.top_ml_factors
        return d


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────

async def compute_risk_score(
    period_id: UUID,
    db: AsyncSession,
) -> RiskAssessmentResult:
    """Compute the full 100-point risk score for a return period.

    Also persists the result in the risk_assessments table and
    links it to the return period.
    """
    metrics = await _load_risk_metrics(period_id, db)
    result = RiskAssessmentResult()

    # Score each category
    result.category_a_score = _score_category_a(metrics, result.risk_flags)
    result.category_b_score = _score_category_b(metrics, result.risk_flags)
    result.category_c_score = _score_category_c(metrics, result.risk_flags)
    result.category_d_score = _score_category_d(metrics, result.risk_flags)
    result.category_e_score = _score_category_e(metrics, result.risk_flags)

    # Total (capped at 100)
    raw = (
        result.category_a_score
        + result.category_b_score
        + result.category_c_score
        + result.category_d_score
        + result.category_e_score
    )
    result.risk_score = min(raw, 100)

    # Level
    result.risk_level = _score_to_level(result.risk_score)

    # ── ML hybrid blend (Phase 3B) ──
    from app.core.config import settings as _settings
    if _settings.ML_RISK_ENABLED:
        ml_pred, blend_wt = await _try_ml_prediction(metrics, db)
        if ml_pred is not None:
            rule_score = result.risk_score
            blended = round((1 - blend_wt) * rule_score + blend_wt * ml_pred.predicted_risk_score)
            result.risk_score = max(0, min(100, blended))
            result.risk_level = _score_to_level(result.risk_score)

            # Populate ML metadata
            result.ml_risk_score = ml_pred.predicted_risk_score
            result.ml_enhanced = True
            result.ml_confidence = ml_pred.confidence
            result.ml_blend_weight = blend_wt
            result.ml_prediction_json = json.dumps(ml_pred.to_dict())

            # Top 5 ML factors for CA transparency
            if ml_pred.feature_importances:
                sorted_feats = sorted(
                    ml_pred.feature_importances.items(),
                    key=lambda x: abs(x[1]), reverse=True,
                )[:5]
                result.top_ml_factors = [
                    {"feature": k, "importance": round(v, 4)}
                    for k, v in sorted_feats
                ]

    # Override: any CRITICAL flag → at least HIGH
    has_critical = any(f.severity == "CRITICAL" for f in result.risk_flags)
    if has_critical and result.risk_level not in ("HIGH", "CRITICAL"):
        result.risk_level = "HIGH"

    # Recommended actions
    result.recommended_actions = _recommend_actions(result.risk_flags)

    # Persist
    await _persist_result(period_id, result, db)

    logger.info(
        "Risk score computed for period %s: %d (%s), flags=%d",
        period_id, result.risk_score, result.risk_level, len(result.risk_flags),
    )
    return result


# ──────────────────────────────────────────────────────────────
# Category A — Data Quality (max 20)
# ──────────────────────────────────────────────────────────────

def _score_category_a(m: RiskMetrics, flags: list[RiskFlag]) -> int:
    score = 0

    # Duplicate invoice numbers: +6 (cap)
    if m.duplicate_invoice_count > 0:
        pts = min(6, m.duplicate_invoice_count * 2)
        score += pts
        flags.append(RiskFlag(
            code="DUP_INVOICE",
            severity="HIGH" if pts >= 4 else "MEDIUM",
            points=pts,
            evidence=f"{m.duplicate_invoice_count} duplicate invoice number(s) found",
        ))

    # Missing B2B GSTIN: +2 each, cap 8
    if m.missing_gstin_b2b_count > 0:
        pts = min(8, m.missing_gstin_b2b_count * 2)
        score += pts
        flags.append(RiskFlag(
            code="MISSING_B2B_GSTIN",
            severity="MEDIUM",
            points=pts,
            evidence=f"{m.missing_gstin_b2b_count} B2B invoice(s) without recipient GSTIN",
        ))

    # POS / tax type mismatch: +3 each, cap 8
    if m.pos_mismatch_count > 0:
        pts = min(8, m.pos_mismatch_count * 3)
        score += pts
        flags.append(RiskFlag(
            code="POS_TAX_MISMATCH",
            severity="MEDIUM",
            points=pts,
            evidence=f"{m.pos_mismatch_count} POS / tax type mismatch(es)",
        ))

    # High amendment ratio (>5%): +4
    total = m.total_outward_invoices + m.total_inward_invoices
    if total > 0 and m.amendment_count / total > 0.05:
        score += 4
        ratio = round(m.amendment_count / total * 100, 1)
        flags.append(RiskFlag(
            code="HIGH_AMENDMENT_RATIO",
            severity="MEDIUM",
            points=4,
            evidence=f"Amendment ratio {ratio}% (>{5}% threshold)",
        ))

    return min(score, 20)


# ──────────────────────────────────────────────────────────────
# Category B — ITC & 2B Reconciliation (max 35)
# ──────────────────────────────────────────────────────────────

def _score_category_b(m: RiskMetrics, flags: list[RiskFlag]) -> int:
    score = 0

    # No 2B uploaded but ITC claimed: +15
    if not m.has_2b_data and m.itc_claimed > 0:
        score += 15
        flags.append(RiskFlag(
            code="NO_2B_ITC_CLAIMED",
            severity="HIGH",
            points=15,
            evidence=f"ITC ₹{m.itc_claimed:,.2f} claimed with no GSTR-2B data uploaded",
        ))

    if m.has_2b_data and m.total_2b_entries > 0:
        # Missing in 2B: min(18, round(18 * ratio))
        if m.missing_in_2b_count > 0:
            ratio = m.missing_in_2b_count / max(m.total_inward_invoices, 1)
            pts = min(18, round(18 * ratio))
            if pts > 0:
                score += pts
                flags.append(RiskFlag(
                    code="MISSING_IN_2B",
                    severity="HIGH" if pts >= 10 else "MEDIUM",
                    points=pts,
                    evidence=f"{m.missing_in_2b_count} purchase invoice(s) not found in GSTR-2B",
                ))

        # Value mismatches: min(10, 2 * count)
        if m.value_mismatch_count > 0:
            pts = min(10, 2 * m.value_mismatch_count)
            score += pts
            flags.append(RiskFlag(
                code="VALUE_MISMATCH_2B",
                severity="MEDIUM",
                points=pts,
                evidence=f"{m.value_mismatch_count} value mismatch(es) between books and 2B",
            ))

    # Suspected blocked ITC: +8
    if m.blocked_itc_count > 0:
        score += 8
        flags.append(RiskFlag(
            code="BLOCKED_ITC",
            severity="HIGH",
            points=8,
            evidence=f"{m.blocked_itc_count} invoice(s) flagged for blocked ITC (Section 17(5))",
        ))

    # ITC ratio anomaly
    if m.output_tax_total > 0:
        if m.itc_ratio > 1.2:
            score += 10
            flags.append(RiskFlag(
                code="ITC_RATIO_EXTREME",
                severity="CRITICAL",
                points=10,
                evidence=f"ITC ratio {m.itc_ratio:.2f} (>1.2× output tax — potential over-claim)",
            ))
        elif m.itc_ratio > 0.9:
            score += 6
            flags.append(RiskFlag(
                code="ITC_RATIO_HIGH",
                severity="HIGH",
                points=6,
                evidence=f"ITC ratio {m.itc_ratio:.2f} (>0.9× output tax)",
            ))

    return min(score, 35)


# ──────────────────────────────────────────────────────────────
# Category C — Liability / Payment / Filing (max 20)
# ──────────────────────────────────────────────────────────────

def _score_category_c(m: RiskMetrics, flags: list[RiskFlag]) -> int:
    score = 0

    # Late filing
    if m.days_past_due > 0:
        if m.days_past_due > 30:
            pts = 12
            sev = "CRITICAL"
        elif m.days_past_due > 7:
            pts = 8
            sev = "HIGH"
        else:
            pts = 5
            sev = "MEDIUM"
        score += pts
        flags.append(RiskFlag(
            code="LATE_FILING",
            severity=sev,
            points=pts,
            evidence=f"Filing overdue by {m.days_past_due} day(s)",
        ))

    # Payment missing (net > 0 but no challan)
    if m.net_payable > 0 and m.payment_count == 0:
        score += 10
        flags.append(RiskFlag(
            code="PAYMENT_MISSING",
            severity="HIGH",
            points=10,
            evidence=f"Net payable ₹{m.net_payable:,.2f} but no payment recorded",
        ))
    elif m.net_payable > 0 and m.total_paid < m.net_payable:
        shortfall = m.net_payable - m.total_paid
        shortfall_pct = float(shortfall / m.net_payable * 100)
        if shortfall_pct > 10:
            pts = 12
        else:
            pts = 8
        score += pts
        flags.append(RiskFlag(
            code="PAYMENT_SHORT",
            severity="HIGH",
            points=pts,
            evidence=f"Payment shortfall ₹{shortfall:,.2f} ({shortfall_pct:.1f}% of liability)",
        ))

    # RCM not addressed
    if m.rcm_total > 0 and m.period_status in ("draft", "data_ready"):
        score += 6
        flags.append(RiskFlag(
            code="RCM_UNADDRESSED",
            severity="MEDIUM",
            points=6,
            evidence=f"RCM liability ₹{m.rcm_total:,.2f} not yet addressed in filing",
        ))

    return min(score, 20)


# ──────────────────────────────────────────────────────────────
# Category D — Behavioral / Anomaly (max 15)
# ──────────────────────────────────────────────────────────────

def _score_category_d(m: RiskMetrics, flags: list[RiskFlag]) -> int:
    score = 0

    # Turnover spike
    if m.avg_turnover_3 > 0 and m.current_turnover > 0:
        ratio = float(m.current_turnover / m.avg_turnover_3)
        if ratio > 2.0:
            score += 10
            flags.append(RiskFlag(
                code="TURNOVER_SPIKE_2X",
                severity="HIGH",
                points=10,
                evidence=f"Turnover {ratio:.1f}× avg of last 3 periods (>2×)",
            ))
        elif ratio > 1.5:
            score += 6
            flags.append(RiskFlag(
                code="TURNOVER_SPIKE_1_5X",
                severity="MEDIUM",
                points=6,
                evidence=f"Turnover {ratio:.1f}× avg of last 3 periods (>1.5×)",
            ))

    # ITC spike
    if m.avg_itc_3 > 0 and m.itc_claimed > 0:
        ratio = float(m.itc_claimed / m.avg_itc_3)
        if ratio > 1.5:
            pts = min(5, round(5 * (ratio - 1.5)))
            pts = max(pts, 1)  # at least 1 point
            score += pts
            flags.append(RiskFlag(
                code="ITC_SPIKE",
                severity="MEDIUM",
                points=pts,
                evidence=f"ITC {ratio:.1f}× avg of last 3 periods",
            ))

    # Amendment trend up 3 consecutive periods
    if len(m.amendment_trend) >= 3:
        if (
            m.amendment_trend[-1] > m.amendment_trend[-2]
            and m.amendment_trend[-2] > m.amendment_trend[-3]
            and m.amendment_trend[-1] > 0
        ):
            score += 3
            flags.append(RiskFlag(
                code="AMENDMENT_TREND_UP",
                severity="LOW",
                points=3,
                evidence=f"Amendments increasing over 3 periods: {m.amendment_trend[-3:]}"
            ))

    return min(score, 15)


# ──────────────────────────────────────────────────────────────
# Category E — Policy / Structural (max 10)
# ──────────────────────────────────────────────────────────────

def _score_category_e(m: RiskMetrics, flags: list[RiskFlag]) -> int:
    score = 0

    # Composition taxpayer claiming ITC: +10 (CRITICAL)
    if m.taxpayer_type == "composition" and m.itc_claimed > 0:
        score += 10
        flags.append(RiskFlag(
            code="COMPOSITION_ITC_CLAIM",
            severity="CRITICAL",
            points=10,
            evidence=f"Composition taxpayer claiming ITC ₹{m.itc_claimed:,.2f} — not allowed",
        ))

    # QRMP cadence issue: +3
    if m.taxpayer_type == "qrmp" and m.filing_mode == "monthly":
        score += 3
        flags.append(RiskFlag(
            code="QRMP_CADENCE_ISSUE",
            severity="LOW",
            points=3,
            evidence="QRMP taxpayer with monthly filing mode — should be quarterly",
        ))

    # E-commerce TCS missing: +5 (placeholder — would check e-commerce invoices)
    # Future enhancement: detect e-commerce supplies without TCS deduction

    return min(score, 10)


# ──────────────────────────────────────────────────────────────
# ML Hybrid Prediction Helper (Phase 3B)
# ──────────────────────────────────────────────────────────────

async def _try_ml_prediction(
    metrics: RiskMetrics,
    db: AsyncSession,
) -> tuple:
    """Attempt ML prediction using the active model.

    Returns (MLPrediction, blend_weight) or (None, 0.0) if no model.
    """
    try:
        from app.core.config import settings as _settings
        from app.domain.services.ml_feature_engineering import metrics_to_features
        from app.domain.services.ml_risk_model import RiskMLModel
        from app.infrastructure.db.repositories.ml_model_repository import MLModelRepository

        repo = MLModelRepository(db)
        artifact = await repo.get_active_model("risk_scoring_v1")
        if artifact is None:
            return (None, 0.0)

        model = RiskMLModel.deserialize(artifact.model_binary)
        fv = metrics_to_features(metrics)
        prediction = model.predict(
            fv.values,
            compute_shap=_settings.ML_RISK_SHAP_ENABLED,
        )

        blend_weight = _settings.ML_RISK_BLEND_WEIGHT
        return (prediction, blend_weight)

    except Exception:
        logger.warning("ML prediction failed — falling back to rule-only", exc_info=True)
        return (None, 0.0)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _score_to_level(score: int) -> str:
    if score >= 70:
        return "CRITICAL"
    if score >= 45:
        return "HIGH"
    if score >= 20:
        return "MEDIUM"
    return "LOW"


# ── Action recommendations ────────────────────────────────────

_ACTION_MAP: dict[str, RecommendedAction] = {
    "DUP_INVOICE": RecommendedAction(
        "Review and de-duplicate invoice numbers",
        "Duplicate invoices inflate output tax and may trigger scrutiny",
    ),
    "MISSING_B2B_GSTIN": RecommendedAction(
        "Add recipient GSTIN to B2B invoices",
        "Missing GSTIN prevents ITC availability for the buyer",
    ),
    "POS_TAX_MISMATCH": RecommendedAction(
        "Verify place of supply and correct tax type (IGST vs CGST+SGST)",
        "POS errors lead to wrong tax classification",
    ),
    "HIGH_AMENDMENT_RATIO": RecommendedAction(
        "Review amendments for correctness before filing",
        "High amendment ratio may attract GST audit attention",
    ),
    "NO_2B_ITC_CLAIMED": RecommendedAction(
        "Upload GSTR-2B data before claiming ITC",
        "ITC without 2B verification is risky under Rule 36(4)",
    ),
    "MISSING_IN_2B": RecommendedAction(
        "Contact suppliers for missing invoices in GSTR-2B",
        "ITC cannot be claimed for invoices absent in 2B",
    ),
    "VALUE_MISMATCH_2B": RecommendedAction(
        "Reconcile value differences with supplier GSTR-1",
        "Value mismatches will block ITC during auto-reconciliation",
    ),
    "BLOCKED_ITC": RecommendedAction(
        "Verify and reverse blocked ITC under Section 17(5)",
        "Claiming blocked ITC leads to demand notices",
    ),
    "ITC_RATIO_EXTREME": RecommendedAction(
        "Audit ITC claims — ratio exceeds output tax by >20%",
        "Department flags ITC ratio >1.0 for verification",
    ),
    "ITC_RATIO_HIGH": RecommendedAction(
        "Review ITC eligibility for high-value claims",
        "ITC ratio >0.9 may attract departmental scrutiny",
    ),
    "LATE_FILING": RecommendedAction(
        "File return immediately to minimize late fee and interest",
        "Late filing attracts ₹50/day (₹20 for nil) + 18% interest",
    ),
    "PAYMENT_MISSING": RecommendedAction(
        "Record challan payment before filing",
        "Filing without payment results in interest liability",
    ),
    "PAYMENT_SHORT": RecommendedAction(
        "Pay remaining liability to avoid interest charges",
        "Short payment attracts 18% interest on the shortfall",
    ),
    "RCM_UNADDRESSED": RecommendedAction(
        "Compute and include RCM liability in GSTR-3B",
        "Missing RCM attracts penalty + interest on discovery",
    ),
    "TURNOVER_SPIKE_2X": RecommendedAction(
        "Verify all high-value invoices in this period",
        "Significant turnover spike may indicate data entry errors",
    ),
    "TURNOVER_SPIKE_1_5X": RecommendedAction(
        "Cross-check turnover with books of accounts",
        "Moderate turnover increase — verify correctness",
    ),
    "ITC_SPIKE": RecommendedAction(
        "Verify large ITC claims against purchase records",
        "Unusual ITC increase requires documentary support",
    ),
    "AMENDMENT_TREND_UP": RecommendedAction(
        "Investigate root cause of increasing amendments",
        "Persistent amendment increases suggest systemic data issues",
    ),
    "COMPOSITION_ITC_CLAIM": RecommendedAction(
        "Remove all ITC claims — composition taxpayers cannot claim ITC",
        "ITC is strictly prohibited under composition scheme",
    ),
    "QRMP_CADENCE_ISSUE": RecommendedAction(
        "Update filing mode to quarterly for QRMP consistency",
        "QRMP taxpayers should file quarterly returns",
    ),
}


def _recommend_actions(flags: list[RiskFlag]) -> list[RecommendedAction]:
    """Map risk flags to recommended corrective actions."""
    actions = []
    seen = set()
    for f in flags:
        if f.code in _ACTION_MAP and f.code not in seen:
            actions.append(_ACTION_MAP[f.code])
            seen.add(f.code)
    return actions


# ── Load metrics from DB ──────────────────────────────────────

async def _load_risk_metrics(
    period_id: UUID,
    db: AsyncSession,
) -> RiskMetrics:
    """Gather all scoring inputs from DB for a single period."""
    m = RiskMetrics()

    # 1. Load ReturnPeriod
    rp_stmt = select(ReturnPeriod).where(ReturnPeriod.id == period_id)
    rp_result = await db.execute(rp_stmt)
    rp = rp_result.scalar_one_or_none()
    if not rp:
        return m

    m.period_status = rp.status
    m.filing_mode = rp.filing_mode or "monthly"
    m.net_payable = (
        (rp.net_payable_igst or Decimal("0"))
        + (rp.net_payable_cgst or Decimal("0"))
        + (rp.net_payable_sgst or Decimal("0"))
    )
    m.rcm_total = (
        (rp.rcm_igst or Decimal("0"))
        + (rp.rcm_cgst or Decimal("0"))
        + (rp.rcm_sgst or Decimal("0"))
    )
    m.itc_claimed = (
        (rp.itc_igst or Decimal("0"))
        + (rp.itc_cgst or Decimal("0"))
        + (rp.itc_sgst or Decimal("0"))
    )
    m.output_tax_total = (
        (rp.output_tax_igst or Decimal("0"))
        + (rp.output_tax_cgst or Decimal("0"))
        + (rp.output_tax_sgst or Decimal("0"))
    )
    m.current_turnover = m.output_tax_total  # proxy via output tax
    m.total_outward_invoices = rp.outward_count or 0
    m.total_inward_invoices = rp.inward_count or 0

    if m.output_tax_total > 0:
        m.itc_ratio = float(m.itc_claimed / m.output_tax_total)

    m.due_date_gstr3b = rp.due_date_gstr3b
    if rp.due_date_gstr3b:
        today = date.today()
        if today > rp.due_date_gstr3b and rp.status not in ("filed", "closed"):
            m.days_past_due = (today - rp.due_date_gstr3b).days

    # 2. Invoice-level metrics
    dup_stmt = (
        select(
            Invoice.invoice_number,
            func.count(Invoice.id).label("cnt"),
        )
        .where(
            and_(
                Invoice.user_id == rp.user_id,
                Invoice.direction == "outward",
            )
        )
        .group_by(Invoice.invoice_number)
        .having(func.count(Invoice.id) > 1)
    )
    dup_result = await db.execute(dup_stmt)
    m.duplicate_invoice_count = len(dup_result.all())

    # Missing GSTIN on B2B outward (recipient_gstin is NULL but total > threshold)
    missing_stmt = select(func.count(Invoice.id)).where(
        and_(
            Invoice.user_id == rp.user_id,
            Invoice.direction == "outward",
            Invoice.recipient_gstin.is_(None),
            Invoice.taxable_value > 250000,  # B2B threshold ₹2.5L
        )
    )
    missing_result = await db.execute(missing_stmt)
    m.missing_gstin_b2b_count = missing_result.scalar() or 0

    # 3. ITC reconciliation metrics
    match_stmt = select(ITCMatch).where(ITCMatch.period_id == period_id)
    match_result = await db.execute(match_stmt)
    matches = list(match_result.scalars().all())

    if matches:
        m.has_2b_data = True
        m.total_2b_entries = len(matches)
        for mtch in matches:
            if mtch.match_status == "matched":
                m.matched_count += 1
            elif mtch.match_status == "missing_in_2b":
                m.missing_in_2b_count += 1
            elif mtch.match_status == "value_mismatch":
                m.value_mismatch_count += 1
            elif mtch.match_status == "missing_in_books":
                m.missing_in_books_count += 1

    # Blocked ITC count
    blocked_stmt = select(func.count(Invoice.id)).where(
        and_(
            Invoice.user_id == rp.user_id,
            Invoice.direction == "inward",
            Invoice.blocked_itc_reason.isnot(None),
        )
    )
    blocked_result = await db.execute(blocked_stmt)
    m.blocked_itc_count = blocked_result.scalar() or 0

    # 4. Payment metrics
    pay_stmt = select(PaymentRecord).where(
        and_(
            PaymentRecord.period_id == period_id,
            PaymentRecord.status == "confirmed",
        )
    )
    pay_result = await db.execute(pay_stmt)
    payments = list(pay_result.scalars().all())
    m.payment_count = len(payments)
    m.total_paid = sum(
        (p.total or Decimal("0")) for p in payments
    )

    # 5. Historical averages (last 3 periods before this one)
    hist_stmt = (
        select(ReturnPeriod)
        .where(
            and_(
                ReturnPeriod.user_id == rp.user_id,
                ReturnPeriod.gstin == rp.gstin,
                ReturnPeriod.period < rp.period,
            )
        )
        .order_by(ReturnPeriod.period.desc())
        .limit(3)
    )
    hist_result = await db.execute(hist_stmt)
    hist_periods = list(hist_result.scalars().all())

    if hist_periods:
        turnovers = [
            (hp.output_tax_igst or Decimal("0"))
            + (hp.output_tax_cgst or Decimal("0"))
            + (hp.output_tax_sgst or Decimal("0"))
            for hp in hist_periods
        ]
        itcs = [
            (hp.itc_igst or Decimal("0"))
            + (hp.itc_cgst or Decimal("0"))
            + (hp.itc_sgst or Decimal("0"))
            for hp in hist_periods
        ]
        m.avg_turnover_3 = sum(turnovers) / len(turnovers) if turnovers else Decimal("0")
        m.avg_itc_3 = sum(itcs) / len(itcs) if itcs else Decimal("0")

    # 6. Taxpayer type (check BusinessClient if linked via GSTIN)
    bc_stmt = select(BusinessClient).where(BusinessClient.gstin == rp.gstin)
    bc_result = await db.execute(bc_stmt)
    bc = bc_result.scalar_one_or_none()
    if bc:
        m.taxpayer_type = bc.taxpayer_type or "regular"

    return m


# ── Persist result ────────────────────────────────────────────

async def _persist_result(
    period_id: UUID,
    result: RiskAssessmentResult,
    db: AsyncSession,
) -> None:
    """Save risk assessment to DB and link to ReturnPeriod."""
    from app.infrastructure.db.repositories.risk_assessment_repository import (
        RiskAssessmentRepository,
    )

    repo = RiskAssessmentRepository(db)
    assessment_dict = result.to_dict()

    # Include ML metadata for persistence
    if result.ml_enhanced:
        assessment_dict["ml_risk_score"] = result.ml_risk_score
        assessment_dict["ml_prediction_json"] = result.ml_prediction_json
        assessment_dict["blend_weight"] = result.ml_blend_weight

    ra = await repo.create_or_update(period_id, assessment_dict)

    # Link to ReturnPeriod
    rp_stmt = select(ReturnPeriod).where(ReturnPeriod.id == period_id)
    rp_result = await db.execute(rp_stmt)
    rp = rp_result.scalar_one_or_none()
    if rp:
        rp.risk_assessment_id = ra.id
        await db.commit()
