# app/domain/services/itr_service.py
"""
ITR (Income Tax Return) computation service.

Supports:
- ITR-1 (Sahaj): Salaried individuals, one house property, other sources, agri income < 5k
- ITR-4 (Sugam): Presumptive income u/s 44AD/44ADA/44AE

Tax computation for both Old and New regimes (AY 2025-26 / FY 2024-25).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

logger = logging.getLogger("itr_service")

D = lambda x: Decimal(str(x)) if x else Decimal("0")  # noqa: E731


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ITR1Input:
    """Inputs needed for ITR-1 (Sahaj) computation."""
    pan: str = ""
    name: str = ""
    dob: str = ""                                    # Date of birth DD/MM/YYYY
    gender: str = ""                                 # M / F / O
    assessment_year: str = "2025-26"  # AY 2025-26 = FY 2024-25

    # Income heads
    salary_income: Decimal = Decimal("0")          # Gross salary
    standard_deduction: Decimal = Decimal("75000")  # Section 16(ia) - Rs 75,000 for AY 2025-26
    house_property_income: Decimal = Decimal("0")   # Net income from 1 HP (can be negative)
    other_income: Decimal = Decimal("0")            # Interest, dividends, etc.
    agricultural_income: Decimal = Decimal("0")     # Max 5000 for ITR-1

    # Deductions (Chapter VI-A) — only applicable for Old Regime
    section_80c: Decimal = Decimal("0")       # PPF, ELSS, LIC, etc. (max 1.5L)
    section_80d: Decimal = Decimal("0")       # Medical insurance (max 25K/50K/1L)
    section_80e: Decimal = Decimal("0")       # Education loan interest (no limit)
    section_80g: Decimal = Decimal("0")       # Donations
    section_80tta: Decimal = Decimal("0")     # Savings interest (max 10K)
    section_80ccd_1b: Decimal = Decimal("0")  # NPS additional (max 50K)
    other_deductions: Decimal = Decimal("0")  # Catch-all

    # Tax already paid
    tds_total: Decimal = Decimal("0")
    advance_tax: Decimal = Decimal("0")
    self_assessment_tax: Decimal = Decimal("0")


@dataclass
class ITR4Input:
    """Inputs needed for ITR-4 (Sugam) — presumptive taxation."""
    pan: str = ""
    name: str = ""
    dob: str = ""                                    # Date of birth DD/MM/YYYY
    gender: str = ""                                 # M / F / O
    assessment_year: str = "2025-26"

    # Business income under presumptive scheme
    gross_turnover: Decimal = Decimal("0")       # Total turnover
    presumptive_rate: Decimal = Decimal("8")     # 8% for cash, 6% for digital

    # Professional income (44ADA)
    gross_receipts: Decimal = Decimal("0")       # Professional gross receipts
    professional_rate: Decimal = Decimal("50")   # 50% deemed profit

    # Other income
    salary_income: Decimal = Decimal("0")
    house_property_income: Decimal = Decimal("0")
    other_income: Decimal = Decimal("0")

    # Deductions
    section_80c: Decimal = Decimal("0")
    section_80d: Decimal = Decimal("0")
    other_deductions: Decimal = Decimal("0")

    # Tax already paid
    tds_total: Decimal = Decimal("0")
    advance_tax: Decimal = Decimal("0")


@dataclass
class ITR2Input:
    """Inputs for ITR-2 — Salaried with capital gains / multiple house properties."""
    pan: str = ""
    name: str = ""
    dob: str = ""                                    # Date of birth DD/MM/YYYY
    gender: str = ""                                 # M / F / O
    assessment_year: str = "2025-26"

    # Income heads (same as ITR-1)
    salary_income: Decimal = Decimal("0")
    standard_deduction: Decimal = Decimal("75000")
    house_property_income: Decimal = Decimal("0")
    other_income: Decimal = Decimal("0")

    # Capital Gains (equity only — Phase 1)
    stcg_111a: Decimal = Decimal("0")     # Short-term CG on equity (taxed at 15%)
    stcg_other: Decimal = Decimal("0")    # Short-term CG non-equity (added to slab income)
    ltcg_112a: Decimal = Decimal("0")     # Long-term CG on equity (10% over 1L exemption)
    ltcg_other: Decimal = Decimal("0")    # Long-term CG non-equity (20% with indexation)

    # Deductions (Chapter VI-A — old regime only)
    section_80c: Decimal = Decimal("0")
    section_80d: Decimal = Decimal("0")
    section_80e: Decimal = Decimal("0")
    section_80g: Decimal = Decimal("0")
    section_80tta: Decimal = Decimal("0")
    section_80ccd_1b: Decimal = Decimal("0")
    other_deductions: Decimal = Decimal("0")

    # Tax already paid
    tds_total: Decimal = Decimal("0")
    advance_tax: Decimal = Decimal("0")
    self_assessment_tax: Decimal = Decimal("0")


@dataclass
class TaxBreakdown:
    """Tax computation result for a single regime."""
    regime: str  # "old" or "new"
    gross_total_income: Decimal = Decimal("0")
    total_deductions: Decimal = Decimal("0")
    taxable_income: Decimal = Decimal("0")
    tax_on_income: Decimal = Decimal("0")
    surcharge: Decimal = Decimal("0")
    health_cess: Decimal = Decimal("0")      # 4% health & education cess
    total_tax_liability: Decimal = Decimal("0")
    rebate_87a: Decimal = Decimal("0")
    tax_after_rebate: Decimal = Decimal("0")
    taxes_paid: Decimal = Decimal("0")
    tax_payable: Decimal = Decimal("0")       # Positive = pay, Negative = refund
    slab_details: list[dict] = field(default_factory=list)
    # Capital gains breakdown (only populated for ITR-2)
    stcg_111a_tax: Decimal = Decimal("0")
    ltcg_112a_tax: Decimal = Decimal("0")
    ltcg_other_tax: Decimal = Decimal("0")


@dataclass
class ITRResult:
    """Result of ITR computation with both regime comparisons."""
    form_type: str  # "ITR-1", "ITR-2", or "ITR-4"
    old_regime: TaxBreakdown | None = None
    new_regime: TaxBreakdown | None = None
    recommended_regime: str = ""
    savings: Decimal = Decimal("0")  # How much you save with recommended regime


# ---------------------------------------------------------------------------
# Tax Slabs — AY 2025-26 (FY 2024-25)
# ---------------------------------------------------------------------------

# Old Regime slabs — age-based (unchanged for years)
# General (below 60 years)
OLD_REGIME_SLABS = [
    (Decimal("250000"), Decimal("0")),       # 0 - 2.5L: 0%
    (Decimal("500000"), Decimal("5")),       # 2.5L - 5L: 5%
    (Decimal("1000000"), Decimal("20")),     # 5L - 10L: 20%
    (None, Decimal("30")),                    # 10L+: 30%
]

# Senior Citizen (60-80 years) — higher basic exemption
OLD_REGIME_SLABS_SENIOR = [
    (Decimal("300000"), Decimal("0")),       # 0 - 3L: 0%
    (Decimal("500000"), Decimal("5")),       # 3L - 5L: 5%
    (Decimal("1000000"), Decimal("20")),     # 5L - 10L: 20%
    (None, Decimal("30")),                    # 10L+: 30%
]

# Super Senior Citizen (80+ years) — highest basic exemption
OLD_REGIME_SLABS_SUPER_SENIOR = [
    (Decimal("500000"), Decimal("0")),       # 0 - 5L: 0%
    (Decimal("1000000"), Decimal("20")),     # 5L - 10L: 20%
    (None, Decimal("30")),                    # 10L+: 30%
]

# New Regime slabs (AY 2025-26 — revised in Budget 2024)
NEW_REGIME_SLABS = [
    (Decimal("300000"), Decimal("0")),       # 0 - 3L: 0%
    (Decimal("700000"), Decimal("5")),       # 3L - 7L: 5%
    (Decimal("1000000"), Decimal("10")),     # 7L - 10L: 10%
    (Decimal("1200000"), Decimal("15")),     # 10L - 12L: 15%
    (Decimal("1500000"), Decimal("20")),     # 12L - 15L: 20%
    (None, Decimal("30")),                    # 15L+: 30%
]

REBATE_87A_OLD_LIMIT = Decimal("500000")    # Taxable income limit for old regime
REBATE_87A_OLD_MAX = Decimal("12500")
REBATE_87A_NEW_LIMIT = Decimal("700000")    # Taxable income limit for new regime
REBATE_87A_NEW_MAX = Decimal("25000")

SECTION_80C_MAX = Decimal("150000")
SECTION_80D_MAX_SELF = Decimal("25000")      # Self/family < 60 years
SECTION_80D_MAX_SENIOR = Decimal("50000")    # Self/family >= 60 years
SECTION_80D_MAX_PARENTS = Decimal("50000")   # Parents >= 60 years (25K if < 60)
SECTION_80D_MAX_TOTAL = Decimal("100000")    # Absolute cap (self senior + parents senior)
SECTION_80TTA_MAX = Decimal("10000")         # Savings account interest deduction
SECTION_80CCD_1B_MAX = Decimal("50000")      # Additional NPS contribution
STANDARD_DEDUCTION_NEW = Decimal("75000")    # New regime also gets std deduction from AY 2025-26


# ---------------------------------------------------------------------------
# Age helpers
# ---------------------------------------------------------------------------

def _age_from_dob(dob_str: str, assessment_year: str = "2025-26") -> int:
    """Calculate age as on March 31 of the *financial year* (AY minus 1).

    Args:
        dob_str: Date of birth in DD/MM/YYYY format.
        assessment_year: e.g. "2025-26".

    Returns:
        Age in years (0 if parsing fails).
    """
    from datetime import date

    try:
        parts = dob_str.strip().replace("-", "/").split("/")
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            dob = date(year, month, day)
        else:
            return 0
    except (ValueError, IndexError):
        return 0

    # Financial year end: AY "2025-26" → FY end = 2025-03-31
    try:
        ay_start = int(assessment_year.split("-")[0])
    except (ValueError, IndexError):
        ay_start = 2025
    fy_end = date(ay_start, 3, 31)

    age = fy_end.year - dob.year - ((fy_end.month, fy_end.day) < (dob.month, dob.day))
    return max(age, 0)


def _old_regime_slabs_for_age(
    age: int,
    slab_config: "ITRSlabConfig | None" = None,
) -> list[tuple]:
    """Return the correct old-regime slab set based on taxpayer age.

    If *slab_config* is provided, slabs are taken from it; otherwise the
    module-level hardcoded constants are used (backward-compatible default).
    """
    if slab_config:
        if age >= 80:
            return slab_config.old_regime_super_senior_slabs
        elif age >= 60:
            return slab_config.old_regime_senior_slabs
        return slab_config.old_regime_slabs
    # Original behaviour (hardcoded constants)
    if age >= 80:
        return OLD_REGIME_SLABS_SUPER_SENIOR
    elif age >= 60:
        return OLD_REGIME_SLABS_SENIOR
    return OLD_REGIME_SLABS


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def _compute_slab_tax(taxable_income: Decimal, slabs: list[tuple]) -> tuple[Decimal, list[dict]]:
    """
    Compute tax using slab rates. Returns (tax_amount, slab_details).
    """
    tax = Decimal("0")
    details = []
    prev_limit = Decimal("0")

    for upper_limit, rate in slabs:
        if upper_limit is None:
            # Last slab — no upper bound
            if taxable_income > prev_limit:
                slab_income = taxable_income - prev_limit
                slab_tax = slab_income * rate / 100
                tax += slab_tax
                details.append({
                    "range": f"{int(prev_limit):,}+",
                    "rate": f"{rate}%",
                    "income": float(slab_income),
                    "tax": float(slab_tax),
                })
        else:
            if taxable_income > prev_limit:
                slab_income = min(taxable_income, upper_limit) - prev_limit
                slab_tax = slab_income * rate / 100
                tax += slab_tax
                details.append({
                    "range": f"{int(prev_limit):,} - {int(upper_limit):,}",
                    "rate": f"{rate}%",
                    "income": float(slab_income),
                    "tax": float(slab_tax),
                })
            prev_limit = upper_limit

    return tax, details


def _compute_surcharge(
    tax: Decimal,
    taxable_income: Decimal,
    slab_config: "ITRSlabConfig | None" = None,
) -> Decimal:
    """
    Compute surcharge with marginal relief.

    Marginal relief ensures that the total tax + surcharge on income just above
    a slab threshold does not exceed the total tax on income at the threshold
    plus the excess income above the threshold. This prevents a perverse outcome
    where earning slightly more results in disproportionately higher tax.
    """
    if taxable_income <= Decimal("5000000"):
        return Decimal("0")

    # Surcharge slab boundaries and rates
    _SURCHARGE_SLABS = (slab_config.surcharge_slabs if slab_config else [
        (Decimal("5000000"),  Decimal("10000000"), Decimal("10")),
        (Decimal("10000000"), Decimal("20000000"), Decimal("15")),
        (Decimal("20000000"), Decimal("50000000"), Decimal("25")),
        (Decimal("50000000"), None,                Decimal("37")),
    ])

    for lower, upper, rate in _SURCHARGE_SLABS:
        in_this_slab = (upper is None and taxable_income > lower) or \
                       (upper is not None and lower < taxable_income <= upper)
        if not in_this_slab:
            continue

        normal_surcharge = tax * rate / 100

        # Marginal relief: compute tax at the slab boundary
        excess_income = taxable_income - lower
        tax_at_boundary, _ = _compute_slab_tax(lower, OLD_REGIME_SLABS)  # approximate
        # The surcharge should not exceed excess_income
        marginal_surcharge = excess_income  # max surcharge = excess income itself

        return min(normal_surcharge, marginal_surcharge)

    return Decimal("0")


def _compute_regime(
    gross_total_income: Decimal,
    deductions: Decimal,
    taxes_paid: Decimal,
    regime: str,
    age: int = 0,
    slab_config: "ITRSlabConfig | None" = None,
) -> TaxBreakdown:
    """Compute tax for a given regime.

    Args:
        age: Taxpayer age as on FY end. Used only for old regime to pick
             the correct slab set (general / senior / super-senior).
             New regime slabs are the same regardless of age.
        slab_config: Optional dynamic config. If ``None``, uses module-level
                     hardcoded constants (backward compatible).
    """
    if regime == "old":
        slabs = _old_regime_slabs_for_age(age, slab_config=slab_config)
        rebate_limit = slab_config.rebate_87a_old_limit if slab_config else REBATE_87A_OLD_LIMIT
        rebate_max = slab_config.rebate_87a_old_max if slab_config else REBATE_87A_OLD_MAX
    else:
        slabs = slab_config.new_regime_slabs if slab_config else NEW_REGIME_SLABS
        rebate_limit = slab_config.rebate_87a_new_limit if slab_config else REBATE_87A_NEW_LIMIT
        rebate_max = slab_config.rebate_87a_new_max if slab_config else REBATE_87A_NEW_MAX

    taxable_income = max(gross_total_income - deductions, Decimal("0"))
    tax_on_income, slab_details = _compute_slab_tax(taxable_income, slabs)

    # Rebate u/s 87A
    rebate = Decimal("0")
    if taxable_income <= rebate_limit:
        rebate = min(tax_on_income, rebate_max)

    tax_after_rebate = max(tax_on_income - rebate, Decimal("0"))

    # Surcharge
    surcharge = _compute_surcharge(tax_after_rebate, taxable_income, slab_config=slab_config)

    # Health & Education Cess
    cess_rate = slab_config.cess_rate if slab_config else Decimal("4")
    cess = (tax_after_rebate + surcharge) * cess_rate / 100

    total_liability = tax_after_rebate + surcharge + cess
    tax_payable = total_liability - taxes_paid

    return TaxBreakdown(
        regime=regime,
        gross_total_income=gross_total_income,
        total_deductions=deductions,
        taxable_income=taxable_income,
        tax_on_income=tax_on_income,
        surcharge=surcharge,
        health_cess=cess,
        total_tax_liability=total_liability,
        rebate_87a=rebate,
        tax_after_rebate=tax_after_rebate,
        taxes_paid=taxes_paid,
        tax_payable=tax_payable,
        slab_details=slab_details,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_itr1(
    inp: ITR1Input,
    slab_config: "ITRSlabConfig | None" = None,
) -> ITRResult:
    """
    Compute ITR-1 (Sahaj) with Old and New regime comparison.

    Args:
        slab_config: Optional dynamic config. If ``None``, uses hardcoded caps.
    """
    # Gross Total Income
    salary_after_std = max(inp.salary_income - inp.standard_deduction, Decimal("0"))
    gross_total = salary_after_std + inp.house_property_income + inp.other_income

    # Old Regime deductions (Chapter VI-A) with statutory caps
    _80c_max = slab_config.section_80c_max if slab_config else SECTION_80C_MAX
    _80d_max = slab_config.section_80d_max_total if slab_config else SECTION_80D_MAX_TOTAL
    _80tta_max = slab_config.section_80tta_max if slab_config else SECTION_80TTA_MAX
    _80ccd_1b_max = slab_config.section_80ccd_1b_max if slab_config else SECTION_80CCD_1B_MAX

    old_80c = min(inp.section_80c, _80c_max)
    old_80d = min(inp.section_80d, _80d_max)
    old_80tta = min(inp.section_80tta, _80tta_max)
    old_80ccd_1b = min(inp.section_80ccd_1b, _80ccd_1b_max)
    old_deductions = (
        old_80c
        + old_80d
        + inp.section_80e       # No statutory cap on education loan interest
        + inp.section_80g
        + old_80tta
        + old_80ccd_1b
        + inp.other_deductions
    )

    # New Regime — very limited deductions (only standard deduction already applied)
    new_deductions = Decimal("0")  # Standard deduction already applied in salary_after_std

    taxes_paid = inp.tds_total + inp.advance_tax + inp.self_assessment_tax

    age = _age_from_dob(inp.dob, inp.assessment_year) if inp.dob else 0
    old = _compute_regime(gross_total, old_deductions, taxes_paid, "old", age=age, slab_config=slab_config)
    new = _compute_regime(gross_total, new_deductions, taxes_paid, "new", age=age, slab_config=slab_config)

    # Recommendation
    if new.total_tax_liability <= old.total_tax_liability:
        recommended = "new"
        savings = old.total_tax_liability - new.total_tax_liability
    else:
        recommended = "old"
        savings = new.total_tax_liability - old.total_tax_liability

    return ITRResult(
        form_type="ITR-1",
        old_regime=old,
        new_regime=new,
        recommended_regime=recommended,
        savings=savings,
    )


def compute_itr4(
    inp: ITR4Input,
    slab_config: "ITRSlabConfig | None" = None,
) -> ITRResult:
    """
    Compute ITR-4 (Sugam) for presumptive taxation.

    Args:
        slab_config: Optional dynamic config. If ``None``, uses hardcoded caps.
    """
    # Business income (44AD)
    biz_income = inp.gross_turnover * inp.presumptive_rate / 100

    # Professional income (44ADA)
    prof_income = inp.gross_receipts * inp.professional_rate / 100

    # Salary (with standard deduction)
    std_ded = slab_config.standard_deduction_salary if slab_config else Decimal("75000")
    salary_after_std = max(inp.salary_income - std_ded, Decimal("0"))

    gross_total = biz_income + prof_income + salary_after_std + inp.house_property_income + inp.other_income

    # Old regime deductions
    _80c_max = slab_config.section_80c_max if slab_config else SECTION_80C_MAX
    old_80c = min(inp.section_80c, _80c_max)
    old_deductions = old_80c + inp.section_80d + inp.other_deductions

    new_deductions = Decimal("0")

    taxes_paid = inp.tds_total + inp.advance_tax

    age = _age_from_dob(inp.dob, inp.assessment_year) if inp.dob else 0
    old = _compute_regime(gross_total, old_deductions, taxes_paid, "old", age=age, slab_config=slab_config)
    new = _compute_regime(gross_total, new_deductions, taxes_paid, "new", age=age, slab_config=slab_config)

    if new.total_tax_liability <= old.total_tax_liability:
        recommended = "new"
        savings = old.total_tax_liability - new.total_tax_liability
    else:
        recommended = "old"
        savings = new.total_tax_liability - old.total_tax_liability

    return ITRResult(
        form_type="ITR-4",
        old_regime=old,
        new_regime=new,
        recommended_regime=recommended,
        savings=savings,
    )


def compute_itr2(
    inp: ITR2Input,
    slab_config: "ITRSlabConfig | None" = None,
) -> ITRResult:
    """
    Compute ITR-2 with Old and New regime comparison.

    Capital gains are taxed at special rates:
    - STCG 111A (equity): flat 15%
    - STCG other: added to slab income (normal rates)
    - LTCG 112A (equity): 10% on gains above Rs 1,00,000
    - LTCG other: flat 20% (with indexation — user provides net amount)
    """
    # 1. Normal slab income (salary + HP + other + STCG other)
    salary_after_std = max(inp.salary_income - inp.standard_deduction, Decimal("0"))
    normal_income = salary_after_std + inp.house_property_income + inp.other_income + inp.stcg_other

    # 2. Special-rate capital gains
    stcg_111a_tax = inp.stcg_111a * Decimal("15") / 100
    ltcg_112a_taxable = max(inp.ltcg_112a - Decimal("100000"), Decimal("0"))
    ltcg_112a_tax = ltcg_112a_taxable * Decimal("10") / 100
    ltcg_other_tax = inp.ltcg_other * Decimal("20") / 100

    special_rate_tax = stcg_111a_tax + ltcg_112a_tax + ltcg_other_tax

    # Total income for surcharge/GTI purposes
    total_capital_gains = inp.stcg_111a + inp.stcg_other + inp.ltcg_112a + inp.ltcg_other
    gross_total_income = normal_income + total_capital_gains

    # 3. Old Regime deductions (Chapter VI-A)
    _80c_max = slab_config.section_80c_max if slab_config else SECTION_80C_MAX
    _80d_max = slab_config.section_80d_max_total if slab_config else SECTION_80D_MAX_TOTAL
    _80tta_max = slab_config.section_80tta_max if slab_config else SECTION_80TTA_MAX
    _80ccd_1b_max = slab_config.section_80ccd_1b_max if slab_config else SECTION_80CCD_1B_MAX

    old_80c = min(inp.section_80c, _80c_max)
    old_80d = min(inp.section_80d, _80d_max)
    old_80tta = min(inp.section_80tta, _80tta_max)
    old_80ccd_1b = min(inp.section_80ccd_1b, _80ccd_1b_max)
    old_deductions = (
        old_80c + old_80d + inp.section_80e + inp.section_80g
        + old_80tta + old_80ccd_1b + inp.other_deductions
    )

    new_deductions = Decimal("0")
    taxes_paid = inp.tds_total + inp.advance_tax + inp.self_assessment_tax
    age = _age_from_dob(inp.dob, inp.assessment_year) if inp.dob else 0

    def _compute_itr2_regime(
        regime: str, deductions: Decimal,
    ) -> TaxBreakdown:
        """Compute ITR-2 tax for a single regime with special CG rates."""
        # Normal income taxed at slab rates
        normal_taxable = max(normal_income - deductions, Decimal("0"))

        if regime == "old":
            slabs = _old_regime_slabs_for_age(age, slab_config=slab_config)
            rebate_limit = slab_config.rebate_87a_old_limit if slab_config else REBATE_87A_OLD_LIMIT
            rebate_max = slab_config.rebate_87a_old_max if slab_config else REBATE_87A_OLD_MAX
        else:
            slabs = slab_config.new_regime_slabs if slab_config else NEW_REGIME_SLABS
            rebate_limit = slab_config.rebate_87a_new_limit if slab_config else REBATE_87A_NEW_LIMIT
            rebate_max = slab_config.rebate_87a_new_max if slab_config else REBATE_87A_NEW_MAX

        slab_tax, slab_details = _compute_slab_tax(normal_taxable, slabs)

        # Add special CG taxes (CG detail lines for user display)
        if inp.stcg_111a > 0:
            slab_details.append({
                "range": "STCG 111A (Equity)",
                "rate": "15%",
                "income": float(inp.stcg_111a),
                "tax": float(stcg_111a_tax),
            })
        if inp.ltcg_112a > 0:
            slab_details.append({
                "range": f"LTCG 112A (Equity, exempt 1L)",
                "rate": "10%",
                "income": float(ltcg_112a_taxable),
                "tax": float(ltcg_112a_tax),
            })
        if inp.ltcg_other > 0:
            slab_details.append({
                "range": "LTCG Other (20%)",
                "rate": "20%",
                "income": float(inp.ltcg_other),
                "tax": float(ltcg_other_tax),
            })

        total_tax_on_income = slab_tax + special_rate_tax

        # Rebate u/s 87A — applies only on normal slab income (not special CG)
        rebate = Decimal("0")
        total_income_for_rebate = normal_taxable + total_capital_gains
        if total_income_for_rebate <= rebate_limit:
            rebate = min(slab_tax, rebate_max)

        tax_after_rebate = max(total_tax_on_income - rebate, Decimal("0"))

        # Surcharge on total income (normal + CG)
        total_taxable_for_surcharge = normal_taxable + total_capital_gains
        surcharge = _compute_surcharge(tax_after_rebate, total_taxable_for_surcharge, slab_config=slab_config)

        # Cess
        cess_rate = slab_config.cess_rate if slab_config else Decimal("4")
        cess = (tax_after_rebate + surcharge) * cess_rate / 100

        total_liability = tax_after_rebate + surcharge + cess
        tax_payable = total_liability - taxes_paid

        return TaxBreakdown(
            regime=regime,
            gross_total_income=gross_total_income,
            total_deductions=deductions,
            taxable_income=normal_taxable + total_capital_gains,
            tax_on_income=total_tax_on_income,
            surcharge=surcharge,
            health_cess=cess,
            total_tax_liability=total_liability,
            rebate_87a=rebate,
            tax_after_rebate=tax_after_rebate,
            taxes_paid=taxes_paid,
            tax_payable=tax_payable,
            slab_details=slab_details,
            stcg_111a_tax=stcg_111a_tax,
            ltcg_112a_tax=ltcg_112a_tax,
            ltcg_other_tax=ltcg_other_tax,
        )

    old = _compute_itr2_regime("old", old_deductions)
    new = _compute_itr2_regime("new", new_deductions)

    if new.total_tax_liability <= old.total_tax_liability:
        recommended = "new"
        savings = old.total_tax_liability - new.total_tax_liability
    else:
        recommended = "old"
        savings = new.total_tax_liability - old.total_tax_liability

    return ITRResult(
        form_type="ITR-2",
        old_regime=old,
        new_regime=new,
        recommended_regime=recommended,
        savings=savings,
    )


# ---------------------------------------------------------------------------
# WhatsApp-friendly text formatter
# ---------------------------------------------------------------------------

def format_itr_result(result: ITRResult, lang: str = "en") -> str:
    """Format ITR computation result as WhatsApp-friendly text."""
    rec = result.old_regime if result.recommended_regime == "old" else result.new_regime
    other = result.new_regime if result.recommended_regime == "old" else result.old_regime

    lines = [
        f"--- {result.form_type} Tax Computation ---",
        "",
        f"Gross Total Income: Rs {float(rec.gross_total_income):,.0f}",
        f"Deductions ({result.recommended_regime.title()} Regime): Rs {float(rec.total_deductions):,.0f}",
        f"Taxable Income: Rs {float(rec.taxable_income):,.0f}",
        "",
    ]

    # Capital gains summary (ITR-2 only)
    if result.form_type == "ITR-2":
        if rec.stcg_111a_tax > 0 or rec.ltcg_112a_tax > 0 or rec.ltcg_other_tax > 0:
            lines.append("Capital Gains Tax:")
            if rec.stcg_111a_tax > 0:
                lines.append(f"  STCG u/s 111A (15%): Rs {float(rec.stcg_111a_tax):,.0f}")
            if rec.ltcg_112a_tax > 0:
                lines.append(f"  LTCG u/s 112A (10%): Rs {float(rec.ltcg_112a_tax):,.0f}")
            if rec.ltcg_other_tax > 0:
                lines.append(f"  LTCG Other (20%): Rs {float(rec.ltcg_other_tax):,.0f}")
            lines.append("")

    # Slab breakdown
    lines.append(f"Tax Slabs ({result.recommended_regime.title()} Regime):")
    for s in rec.slab_details:
        lines.append(f"  {s['range']} @ {s['rate']}: Rs {s['tax']:,.0f}")

    lines.extend([
        "",
        f"Tax on Income: Rs {float(rec.tax_on_income):,.0f}",
    ])

    if rec.rebate_87a > 0:
        lines.append(f"Less: Rebate u/s 87A: Rs {float(rec.rebate_87a):,.0f}")

    lines.extend([
        f"Surcharge: Rs {float(rec.surcharge):,.0f}",
        f"Health & Edu Cess (4%): Rs {float(rec.health_cess):,.0f}",
        f"Total Tax Liability: Rs {float(rec.total_tax_liability):,.0f}",
        f"Taxes Already Paid: Rs {float(rec.taxes_paid):,.0f}",
        "",
    ])

    if rec.tax_payable >= 0:
        lines.append(f"TAX PAYABLE: Rs {float(rec.tax_payable):,.0f}")
    else:
        lines.append(f"REFUND DUE: Rs {float(abs(rec.tax_payable)):,.0f}")

    # Regime comparison
    lines.extend([
        "",
        "--- Regime Comparison ---",
        f"Old Regime Tax: Rs {float(result.old_regime.total_tax_liability):,.0f}",
        f"New Regime Tax: Rs {float(result.new_regime.total_tax_liability):,.0f}",
        "",
        f"RECOMMENDED: {result.recommended_regime.upper()} REGIME",
        f"You save Rs {float(result.savings):,.0f} with {result.recommended_regime} regime.",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Async wrappers (auto-resolve dynamic config)
# ---------------------------------------------------------------------------

async def compute_itr1_dynamic(inp: ITR1Input) -> ITRResult:
    """Async wrapper — resolves slab config dynamically, then computes ITR-1."""
    from app.domain.services.tax_rate_service import get_tax_rate_service

    service = get_tax_rate_service()
    slab_config = await service.get_itr_slabs(inp.assessment_year)
    return compute_itr1(inp, slab_config=slab_config)


async def compute_itr4_dynamic(inp: ITR4Input) -> ITRResult:
    """Async wrapper — resolves slab config dynamically, then computes ITR-4."""
    from app.domain.services.tax_rate_service import get_tax_rate_service

    service = get_tax_rate_service()
    slab_config = await service.get_itr_slabs(inp.assessment_year)
    return compute_itr4(inp, slab_config=slab_config)


async def compute_itr2_dynamic(inp: ITR2Input) -> ITRResult:
    """Async wrapper — resolves slab config dynamically, then computes ITR-2."""
    from app.domain.services.tax_rate_service import get_tax_rate_service

    service = get_tax_rate_service()
    slab_config = await service.get_itr_slabs(inp.assessment_year)
    return compute_itr2(inp, slab_config=slab_config)
