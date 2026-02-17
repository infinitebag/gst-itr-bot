# tests/test_feature_registry_phases.py
"""Tests for updated feature registry (Phases 6-10 features)."""

from app.domain.services.feature_registry import get_all_features_fallback, _ALL_FEATURES


def test_all_features_count():
    """After Phase 6-10, we should have 14 GST features."""
    features = get_all_features_fallback()
    assert len(features) == 14


def test_new_features_present():
    codes = {f["code"] for f in _ALL_FEATURES}
    assert "credit_check" in codes
    assert "filing_status" in codes
    assert "refund_tracking" in codes
    assert "notice_mgmt" in codes
    assert "export_services" in codes


def test_einvoice_has_whatsapp_state():
    einv = next(f for f in _ALL_FEATURES if f["code"] == "e_invoice")
    assert einv["whatsapp_state"] == "EINVOICE_MENU"


def test_ewaybill_has_whatsapp_state():
    ewb = next(f for f in _ALL_FEATURES if f["code"] == "e_waybill")
    assert ewb["whatsapp_state"] == "EWAYBILL_MENU"


def test_multi_gstin_has_whatsapp_state():
    mg = next(f for f in _ALL_FEATURES if f["code"] == "multi_gstin")
    assert mg["whatsapp_state"] == "MULTI_GSTIN_MENU"


def test_features_sorted_by_display_order():
    orders = [f["display_order"] for f in _ALL_FEATURES]
    assert orders == sorted(orders)


def test_all_features_have_i18n_keys():
    for f in _ALL_FEATURES:
        assert f["i18n_key"] is not None
        assert f["i18n_key"].startswith("GST_MENU_ITEM_")


def test_all_features_have_category():
    for f in _ALL_FEATURES:
        assert f["category"] == "gst"


def test_fallback_returns_copy():
    """get_all_features_fallback should return a new list (not the original)."""
    features1 = get_all_features_fallback()
    features2 = get_all_features_fallback()
    assert features1 is not features2
    assert features1 == features2
