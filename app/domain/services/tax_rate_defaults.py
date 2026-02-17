# app/domain/services/tax_rate_defaults.py
"""
Hardcoded tax-rate fallback — Layer 4 (last resort).

These match the constants previously hardcoded in itr_service.py and
tax_analytics.py. Used when Redis, PostgreSQL, and OpenAI are all unavailable.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.models.tax_rate_config import GSTRateConfig, ITRSlabConfig


def default_itr_slabs(assessment_year: str = "2025-26") -> ITRSlabConfig:
    """Return the hardcoded ITR slab config for the given AY."""
    return ITRSlabConfig(
        assessment_year=assessment_year,
        old_regime_slabs=[
            (Decimal("250000"), Decimal("0")),
            (Decimal("500000"), Decimal("5")),
            (Decimal("1000000"), Decimal("20")),
            (None, Decimal("30")),
        ],
        old_regime_senior_slabs=[
            (Decimal("300000"), Decimal("0")),
            (Decimal("500000"), Decimal("5")),
            (Decimal("1000000"), Decimal("20")),
            (None, Decimal("30")),
        ],
        old_regime_super_senior_slabs=[
            (Decimal("500000"), Decimal("0")),
            (Decimal("1000000"), Decimal("20")),
            (None, Decimal("30")),
        ],
        new_regime_slabs=[
            (Decimal("300000"), Decimal("0")),
            (Decimal("700000"), Decimal("5")),
            (Decimal("1000000"), Decimal("10")),
            (Decimal("1200000"), Decimal("15")),
            (Decimal("1500000"), Decimal("20")),
            (None, Decimal("30")),
        ],
        rebate_87a_old_limit=Decimal("500000"),
        rebate_87a_old_max=Decimal("12500"),
        rebate_87a_new_limit=Decimal("700000"),
        rebate_87a_new_max=Decimal("25000"),
        section_80c_max=Decimal("150000"),
        section_80d_max_self=Decimal("25000"),
        section_80d_max_senior=Decimal("50000"),
        section_80d_max_parents=Decimal("50000"),
        section_80d_max_total=Decimal("100000"),
        section_80tta_max=Decimal("10000"),
        section_80ccd_1b_max=Decimal("50000"),
        standard_deduction_salary=Decimal("75000"),
        standard_deduction_new_regime=Decimal("75000"),
        surcharge_slabs=[
            (Decimal("5000000"), Decimal("10000000"), Decimal("10")),
            (Decimal("10000000"), Decimal("20000000"), Decimal("15")),
            (Decimal("20000000"), Decimal("50000000"), Decimal("25")),
            (Decimal("50000000"), None, Decimal("37")),
        ],
        cess_rate=Decimal("4"),
        source="hardcoded",
    )


def default_gst_rates() -> GSTRateConfig:
    """Return the hardcoded GST rate set."""
    return GSTRateConfig(
        valid_rates={0, 0.1, 0.25, 1.5, 3, 5, 6, 7.5, 12, 14, 18, 28},
        source="hardcoded",
    )
