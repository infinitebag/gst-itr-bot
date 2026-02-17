# tests/test_gst_wizard.py
"""Tests for GST explainer service (Phase 7A wizard)."""

import pytest
from app.domain.services.gst_explainer import (
    explain_liability,
    detect_nil_return,
    compute_sales_tax,
    compute_purchase_credit,
    format_simple_summary,
    format_risk_factors,
)


def test_explain_liability():
    result = explain_liability(15300, 8200, "en")
    assert "15,300" in result
    assert "8,200" in result
    assert "7,100" in result


def test_detect_nil_return_empty():
    assert detect_nil_return([]) is True


def test_detect_nil_return_with_invoices():
    assert detect_nil_return([{"total_amount": 1000}]) is False


def test_detect_nil_return_zero_amounts():
    assert detect_nil_return([{"total_amount": 0}, {"total_amount": 0}]) is True


def test_compute_sales_tax():
    invoices = [
        {"cgst_amount": 100, "sgst_amount": 100, "igst_amount": 0},
        {"cgst_amount": 200, "sgst_amount": 200, "igst_amount": 50},
    ]
    result = compute_sales_tax(invoices)
    assert result == 650.0


def test_compute_purchase_credit():
    invoices = [
        {"cgst_amount": 50, "sgst_amount": 50, "igst_amount": 0},
        {"cgst_amount": 100, "sgst_amount": 100, "igst_amount": 25},
    ]
    result = compute_purchase_credit(invoices)
    assert result == 325.0


def test_format_simple_summary():
    sales = [{"cgst_amount": 1000, "sgst_amount": 1000, "igst_amount": 0}]
    purchases = [{"cgst_amount": 500, "sgst_amount": 500, "igst_amount": 0}]
    result = format_simple_summary(sales, purchases, "en", "small")
    assert "Sales Tax" in result
    assert "Purchase Credit" in result
    assert "Amount to Pay" in result


def test_format_risk_factors_with_dict():
    """format_risk_factors expects an object with a factor_scores dict attribute."""
    class MockAssessment:
        factor_scores = {
            "high_value_invoices": 0.85,
            "late_filing": 0.55,
            "input_output_ratio": 0.20,
        }
    result = format_risk_factors(MockAssessment())
    assert "High Value Invoices" in result
    assert "Late Filing" in result


def test_format_risk_factors_none():
    class MockAssessment:
        factor_scores = None
    result = format_risk_factors(MockAssessment())
    assert "No" in result or "factors" in result.lower()


def test_format_risk_factors_empty_dict():
    class MockAssessment:
        factor_scores = {}
    result = format_risk_factors(MockAssessment())
    assert "No" in result or "factors" in result.lower()
