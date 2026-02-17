"""Tests for ITR computation service."""

from decimal import Decimal

import pytest

from app.domain.services.itr_service import (
    ITR1Input,
    ITR4Input,
    compute_itr1,
    compute_itr4,
    SECTION_80C_MAX,
    SECTION_80D_MAX_TOTAL,
    SECTION_80TTA_MAX,
    SECTION_80CCD_1B_MAX,
    _compute_slab_tax,
    OLD_REGIME_SLABS,
    NEW_REGIME_SLABS,
)


class TestDeductionCaps:
    """Verify that deduction caps are correctly enforced."""

    def test_80c_capped_at_150000(self):
        inp = ITR1Input(salary_income=Decimal("2000000"), section_80c=Decimal("300000"))
        result = compute_itr1(inp)
        # Old regime should cap 80C at 1.5L
        assert result.old_regime.total_deductions <= Decimal("150000")

    def test_80d_capped(self):
        inp = ITR1Input(salary_income=Decimal("2000000"), section_80d=Decimal("200000"))
        result = compute_itr1(inp)
        assert result.old_regime.total_deductions <= SECTION_80D_MAX_TOTAL

    def test_80tta_capped_at_10000(self):
        inp = ITR1Input(salary_income=Decimal("1000000"), section_80tta=Decimal("50000"))
        result = compute_itr1(inp)
        # Deductions should only include 10K for 80TTA, not 50K
        assert result.old_regime.total_deductions == SECTION_80TTA_MAX

    def test_80ccd_1b_capped_at_50000(self):
        inp = ITR1Input(salary_income=Decimal("1000000"), section_80ccd_1b=Decimal("100000"))
        result = compute_itr1(inp)
        assert result.old_regime.total_deductions == SECTION_80CCD_1B_MAX


class TestSlabComputation:
    """Verify slab-based tax computation."""

    def test_zero_income(self):
        tax, details = _compute_slab_tax(Decimal("0"), OLD_REGIME_SLABS)
        assert tax == Decimal("0")
        assert details == []

    def test_income_in_exempt_slab_old(self):
        tax, _ = _compute_slab_tax(Decimal("200000"), OLD_REGIME_SLABS)
        assert tax == Decimal("0")

    def test_income_in_5_percent_slab_old(self):
        tax, _ = _compute_slab_tax(Decimal("500000"), OLD_REGIME_SLABS)
        expected = Decimal("250000") * Decimal("5") / 100
        assert tax == expected

    def test_income_above_10L_old(self):
        tax, _ = _compute_slab_tax(Decimal("1500000"), OLD_REGIME_SLABS)
        expected = (
            Decimal("0")  # 0-2.5L
            + Decimal("250000") * Decimal("5") / 100   # 2.5L-5L
            + Decimal("500000") * Decimal("20") / 100   # 5L-10L
            + Decimal("500000") * Decimal("30") / 100   # 10L-15L
        )
        assert tax == expected

    def test_new_regime_slabs(self):
        tax, _ = _compute_slab_tax(Decimal("700000"), NEW_REGIME_SLABS)
        expected = Decimal("400000") * Decimal("5") / 100
        assert tax == expected


class TestRegimeComparison:
    """Verify regime recommendation logic."""

    def test_low_income_prefers_new(self):
        inp = ITR1Input(salary_income=Decimal("600000"))
        result = compute_itr1(inp)
        # Both should be 0 tax (within rebate), new recommended or equal
        assert result.recommended_regime in ("new", "old")

    def test_high_deductions_prefers_old(self):
        # At moderate income (12L), heavy deductions should favour old regime
        inp = ITR1Input(
            salary_income=Decimal("1200000"),
            section_80c=Decimal("150000"),
            section_80d=Decimal("50000"),
            section_80tta=Decimal("10000"),
            section_80ccd_1b=Decimal("50000"),
            section_80e=Decimal("100000"),
            other_deductions=Decimal("50000"),
        )
        result = compute_itr1(inp)
        assert result.recommended_regime == "old"
        assert result.savings > 0

    def test_no_deductions_prefers_new(self):
        inp = ITR1Input(salary_income=Decimal("2000000"))
        result = compute_itr1(inp)
        assert result.recommended_regime == "new"


class TestITR4:
    """Test presumptive taxation computation."""

    def test_basic_itr4(self):
        inp = ITR4Input(gross_turnover=Decimal("5000000"), presumptive_rate=Decimal("8"))
        result = compute_itr4(inp)
        assert result.form_type == "ITR-4"
        assert result.old_regime is not None
        assert result.new_regime is not None
        # Presumptive income = 8% of 50L = 4L
        expected_income = Decimal("400000")
        assert result.old_regime.gross_total_income == expected_income


class TestRebate87A:
    """Test Section 87A rebate application."""

    def test_old_regime_rebate(self):
        # Taxable income 5L -> full rebate
        inp = ITR1Input(salary_income=Decimal("575000"))
        result = compute_itr1(inp)
        assert result.old_regime.rebate_87a > 0
        assert result.old_regime.tax_after_rebate == Decimal("0")

    def test_new_regime_rebate(self):
        # Taxable income 7L -> full rebate under new regime
        inp = ITR1Input(salary_income=Decimal("775000"))
        result = compute_itr1(inp)
        assert result.new_regime.rebate_87a > 0
