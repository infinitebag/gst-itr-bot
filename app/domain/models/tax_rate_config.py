# app/domain/models/tax_rate_config.py
"""
Domain dataclasses for dynamic tax rate configuration.

ITRSlabConfig: All income-tax parameters for a single assessment year.
GSTRateConfig: Set of valid GST rates used for anomaly detection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class ITRSlabConfig:
    """All income-tax parameters for one assessment year."""

    assessment_year: str = "2025-26"

    # Progressive slab lists: [(upper_limit_or_None, rate_percent), ...]
    old_regime_slabs: list[tuple[Decimal | None, Decimal]] = field(default_factory=lambda: [
        (Decimal("250000"), Decimal("0")),
        (Decimal("500000"), Decimal("5")),
        (Decimal("1000000"), Decimal("20")),
        (None, Decimal("30")),
    ])
    old_regime_senior_slabs: list[tuple[Decimal | None, Decimal]] = field(default_factory=lambda: [
        (Decimal("300000"), Decimal("0")),
        (Decimal("500000"), Decimal("5")),
        (Decimal("1000000"), Decimal("20")),
        (None, Decimal("30")),
    ])
    old_regime_super_senior_slabs: list[tuple[Decimal | None, Decimal]] = field(default_factory=lambda: [
        (Decimal("500000"), Decimal("0")),
        (Decimal("1000000"), Decimal("20")),
        (None, Decimal("30")),
    ])
    new_regime_slabs: list[tuple[Decimal | None, Decimal]] = field(default_factory=lambda: [
        (Decimal("300000"), Decimal("0")),
        (Decimal("700000"), Decimal("5")),
        (Decimal("1000000"), Decimal("10")),
        (Decimal("1200000"), Decimal("15")),
        (Decimal("1500000"), Decimal("20")),
        (None, Decimal("30")),
    ])

    # Rebate u/s 87A
    rebate_87a_old_limit: Decimal = Decimal("500000")
    rebate_87a_old_max: Decimal = Decimal("12500")
    rebate_87a_new_limit: Decimal = Decimal("700000")
    rebate_87a_new_max: Decimal = Decimal("25000")

    # Deduction caps
    section_80c_max: Decimal = Decimal("150000")
    section_80d_max_self: Decimal = Decimal("25000")
    section_80d_max_senior: Decimal = Decimal("50000")
    section_80d_max_parents: Decimal = Decimal("50000")
    section_80d_max_total: Decimal = Decimal("100000")
    section_80tta_max: Decimal = Decimal("10000")
    section_80ccd_1b_max: Decimal = Decimal("50000")

    # Standard deductions
    standard_deduction_salary: Decimal = Decimal("75000")
    standard_deduction_new_regime: Decimal = Decimal("75000")

    # Surcharge slabs: [(lower_threshold, upper_threshold_or_None, rate_percent), ...]
    surcharge_slabs: list[tuple[Decimal, Decimal | None, Decimal]] = field(default_factory=lambda: [
        (Decimal("5000000"), Decimal("10000000"), Decimal("10")),
        (Decimal("10000000"), Decimal("20000000"), Decimal("15")),
        (Decimal("20000000"), Decimal("50000000"), Decimal("25")),
        (Decimal("50000000"), None, Decimal("37")),
    ])

    # Cess
    cess_rate: Decimal = Decimal("4")

    # Metadata
    source: str = "hardcoded"  # "hardcoded", "manual", "openai"

    # ---- serialization ----

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for Redis / DB storage."""

        def _slab_list(slabs: list[tuple]) -> list[list]:
            return [[str(s[0]) if s[0] is not None else None, str(s[1])] for s in slabs]

        def _surcharge_list(slabs: list[tuple]) -> list[list]:
            return [
                [str(s[0]), str(s[1]) if s[1] is not None else None, str(s[2])]
                for s in slabs
            ]

        return {
            "assessment_year": self.assessment_year,
            "old_regime_slabs": _slab_list(self.old_regime_slabs),
            "old_regime_senior_slabs": _slab_list(self.old_regime_senior_slabs),
            "old_regime_super_senior_slabs": _slab_list(self.old_regime_super_senior_slabs),
            "new_regime_slabs": _slab_list(self.new_regime_slabs),
            "rebate_87a_old_limit": str(self.rebate_87a_old_limit),
            "rebate_87a_old_max": str(self.rebate_87a_old_max),
            "rebate_87a_new_limit": str(self.rebate_87a_new_limit),
            "rebate_87a_new_max": str(self.rebate_87a_new_max),
            "section_80c_max": str(self.section_80c_max),
            "section_80d_max_self": str(self.section_80d_max_self),
            "section_80d_max_senior": str(self.section_80d_max_senior),
            "section_80d_max_parents": str(self.section_80d_max_parents),
            "section_80d_max_total": str(self.section_80d_max_total),
            "section_80tta_max": str(self.section_80tta_max),
            "section_80ccd_1b_max": str(self.section_80ccd_1b_max),
            "standard_deduction_salary": str(self.standard_deduction_salary),
            "standard_deduction_new_regime": str(self.standard_deduction_new_regime),
            "surcharge_slabs": _surcharge_list(self.surcharge_slabs),
            "cess_rate": str(self.cess_rate),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ITRSlabConfig:
        """Reconstruct from a stored JSON dict."""

        def _parse_slabs(raw: list) -> list[tuple[Decimal | None, Decimal]]:
            result: list[tuple[Decimal | None, Decimal]] = []
            for entry in raw:
                limit = Decimal(str(entry[0])) if entry[0] is not None else None
                rate = Decimal(str(entry[1]))
                result.append((limit, rate))
            return result

        def _parse_surcharge(raw: list) -> list[tuple[Decimal, Decimal | None, Decimal]]:
            result: list[tuple[Decimal, Decimal | None, Decimal]] = []
            for entry in raw:
                lower = Decimal(str(entry[0]))
                upper = Decimal(str(entry[1])) if entry[1] is not None else None
                rate = Decimal(str(entry[2]))
                result.append((lower, upper, rate))
            return result

        def _d(key: str, default: str = "0") -> Decimal:
            val = data.get(key)
            return Decimal(str(val)) if val is not None else Decimal(default)

        return cls(
            assessment_year=data.get("assessment_year", "2025-26"),
            old_regime_slabs=_parse_slabs(data["old_regime_slabs"]) if "old_regime_slabs" in data else cls.old_regime_slabs,
            old_regime_senior_slabs=_parse_slabs(data["old_regime_senior_slabs"]) if "old_regime_senior_slabs" in data else cls.old_regime_senior_slabs,
            old_regime_super_senior_slabs=_parse_slabs(data["old_regime_super_senior_slabs"]) if "old_regime_super_senior_slabs" in data else cls.old_regime_super_senior_slabs,
            new_regime_slabs=_parse_slabs(data["new_regime_slabs"]) if "new_regime_slabs" in data else cls.new_regime_slabs,
            rebate_87a_old_limit=_d("rebate_87a_old_limit", "500000"),
            rebate_87a_old_max=_d("rebate_87a_old_max", "12500"),
            rebate_87a_new_limit=_d("rebate_87a_new_limit", "700000"),
            rebate_87a_new_max=_d("rebate_87a_new_max", "25000"),
            section_80c_max=_d("section_80c_max", "150000"),
            section_80d_max_self=_d("section_80d_max_self", "25000"),
            section_80d_max_senior=_d("section_80d_max_senior", "50000"),
            section_80d_max_parents=_d("section_80d_max_parents", "50000"),
            section_80d_max_total=_d("section_80d_max_total", "100000"),
            section_80tta_max=_d("section_80tta_max", "10000"),
            section_80ccd_1b_max=_d("section_80ccd_1b_max", "50000"),
            standard_deduction_salary=_d("standard_deduction_salary", "75000"),
            standard_deduction_new_regime=_d("standard_deduction_new_regime", "75000"),
            surcharge_slabs=_parse_surcharge(data["surcharge_slabs"]) if "surcharge_slabs" in data else cls.surcharge_slabs,
            cess_rate=_d("cess_rate", "4"),
            source=data.get("source", "hardcoded"),
        )


@dataclass
class GSTRateConfig:
    """Valid GST rate set for anomaly detection / validation."""

    valid_rates: set[float] = field(
        default_factory=lambda: {0, 0.1, 0.25, 1.5, 3, 5, 6, 7.5, 12, 14, 18, 28},
    )
    source: str = "hardcoded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid_rates": sorted(self.valid_rates),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GSTRateConfig:
        return cls(
            valid_rates=set(data.get("valid_rates", [0, 0.1, 0.25, 1.5, 3, 5, 6, 7.5, 12, 14, 18, 28])),
            source=data.get("source", "hardcoded"),
        )
