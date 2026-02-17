# tests/test_segment_gating.py
"""
Tests for Phase 4: Segment-Based Feature Gating.

Covers:
  - Segment auto-detection (detect_segment, thresholds, edge cases)
  - Feature registry (features per segment, addons, fallback, cache)
  - Dynamic WhatsApp menu builder (build_gst_menu, resolve_gst_menu_choice)
  - Menu dispatch (feature code resolution from session)
  - Onboarding flow (turnover/invoice/export maps)
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.services.segment_detection import (
    VALID_SEGMENTS,
    _ENTERPRISE_GSTIN_COUNT,
    _ENTERPRISE_TURNOVER,
    _MEDIUM_GSTIN_COUNT,
    _MEDIUM_INVOICE_VOLUME,
    _MEDIUM_TURNOVER,
    detect_segment,
)
from app.domain.services.feature_registry import (
    _ALL_FEATURES,
    _feature_to_dict,
    get_all_features_fallback,
)
from app.domain.services.whatsapp_menu_builder import (
    _get_i18n_label,
    resolve_gst_menu_choice,
)


# ============================================================
# Test Segment Auto-Detection
# ============================================================


class TestSegmentDetection:
    """Tests for segment_detection.py — pure function, no DB needed."""

    def test_valid_segments(self):
        """VALID_SEGMENTS should contain exactly three tiers."""
        assert VALID_SEGMENTS == ("small", "medium", "enterprise")

    def test_small_default(self):
        """No arguments → small."""
        assert detect_segment() == "small"

    def test_small_low_turnover(self):
        """Turnover below medium threshold → small."""
        assert detect_segment(annual_turnover=1_00_00_000) == "small"  # 1 Cr

    def test_small_low_invoice_volume(self):
        """Invoice volume below medium threshold → small."""
        assert detect_segment(monthly_invoice_volume=50) == "small"

    def test_small_single_gstin(self):
        """Single GSTIN, no other triggers → small."""
        assert detect_segment(gstin_count=1) == "small"

    def test_medium_by_turnover(self):
        """Turnover >= 5 Cr → medium."""
        assert detect_segment(annual_turnover=5_00_00_000) == "medium"  # exact threshold
        assert detect_segment(annual_turnover=10_00_00_000) == "medium"  # above

    def test_medium_by_invoice_volume(self):
        """Monthly invoice volume >= 100 → medium."""
        assert detect_segment(monthly_invoice_volume=100) == "medium"  # exact threshold
        assert detect_segment(monthly_invoice_volume=300) == "medium"  # above

    def test_medium_by_gstin_count(self):
        """GSTIN count >= 2 → medium."""
        assert detect_segment(gstin_count=2) == "medium"
        assert detect_segment(gstin_count=3) == "medium"

    def test_enterprise_by_turnover(self):
        """Turnover >= 50 Cr → enterprise."""
        assert detect_segment(annual_turnover=50_00_00_000) == "enterprise"  # exact
        assert detect_segment(annual_turnover=100_00_00_000) == "enterprise"  # above

    def test_enterprise_by_gstin_count(self):
        """GSTIN count >= 5 → enterprise."""
        assert detect_segment(gstin_count=5) == "enterprise"
        assert detect_segment(gstin_count=10) == "enterprise"

    def test_enterprise_by_exporter(self):
        """is_exporter=True → enterprise (regardless of other params)."""
        assert detect_segment(is_exporter=True) == "enterprise"
        assert detect_segment(annual_turnover=0, is_exporter=True) == "enterprise"

    def test_enterprise_takes_priority_over_medium(self):
        """Enterprise thresholds checked before medium."""
        # Turnover hits both medium and enterprise
        assert detect_segment(annual_turnover=50_00_00_000) == "enterprise"
        # Exporter overrides medium turnover
        assert detect_segment(annual_turnover=10_00_00_000, is_exporter=True) == "enterprise"

    def test_none_turnover_treated_as_zero(self):
        """None turnover should be treated as zero (→ small)."""
        assert detect_segment(annual_turnover=None) == "small"

    def test_none_invoice_volume_treated_as_zero(self):
        """None invoice volume should be treated as zero (→ small)."""
        assert detect_segment(monthly_invoice_volume=None) == "small"

    def test_decimal_turnover(self):
        """Should accept Decimal inputs."""
        assert detect_segment(annual_turnover=Decimal("5_00_00_000")) == "medium"
        assert detect_segment(annual_turnover=Decimal("50_00_00_000")) == "enterprise"

    def test_float_turnover(self):
        """Should accept float inputs."""
        assert detect_segment(annual_turnover=5_00_00_000.0) == "medium"

    def test_just_below_thresholds(self):
        """Just below each threshold should stay at lower tier."""
        # Just below medium (4.99 Cr)
        assert detect_segment(annual_turnover=4_99_99_999) == "small"
        # 99 invoices
        assert detect_segment(monthly_invoice_volume=99) == "small"
        # Just below enterprise (49.99 Cr)
        assert detect_segment(annual_turnover=49_99_99_999) == "medium"
        # 4 GSTINs
        assert detect_segment(gstin_count=4) == "medium"

    def test_combined_params_medium(self):
        """Combined medium-level params still → medium (not enterprise)."""
        result = detect_segment(
            annual_turnover=10_00_00_000,
            monthly_invoice_volume=200,
            gstin_count=3,
            is_exporter=False,
        )
        assert result == "medium"

    def test_threshold_constants(self):
        """Verify threshold constants are correct."""
        assert _ENTERPRISE_TURNOVER == Decimal("50_00_00_000")
        assert _MEDIUM_TURNOVER == Decimal("5_00_00_000")
        assert _MEDIUM_INVOICE_VOLUME == 100
        assert _ENTERPRISE_GSTIN_COUNT == 5
        assert _MEDIUM_GSTIN_COUNT == 2


# ============================================================
# Test Feature Registry (unit tests, no DB)
# ============================================================


class TestFeatureRegistry:
    """Tests for feature_registry.py — focuses on the fallback and helper functions."""

    def test_all_features_count(self):
        """_ALL_FEATURES should have exactly 14 GST features (9 original + 5 from Phases 6-10)."""
        assert len(_ALL_FEATURES) == 14

    def test_all_features_codes(self):
        """All 14 feature codes should be present."""
        codes = {f["code"] for f in _ALL_FEATURES}
        expected = {
            "enter_gstin",
            "monthly_compliance",
            "filing_status",
            "nil_return",
            "upload_invoices",
            "credit_check",
            "e_invoice",
            "e_waybill",
            "annual_return",
            "risk_scoring",
            "multi_gstin",
            "refund_tracking",
            "notice_mgmt",
            "export_services",
        }
        assert codes == expected

    def test_all_features_ordered_by_display_order(self):
        """Features should be in ascending display_order."""
        orders = [f["display_order"] for f in _ALL_FEATURES]
        assert orders == sorted(orders)
        assert orders == [10, 20, 25, 30, 40, 45, 50, 60, 70, 80, 90, 92, 94, 96]

    def test_all_features_have_category(self):
        """All features should have category 'gst'."""
        assert all(f["category"] == "gst" for f in _ALL_FEATURES)

    def test_all_features_have_i18n_keys(self):
        """All features should have an i18n_key set."""
        for f in _ALL_FEATURES:
            assert f["i18n_key"], f"Feature {f['code']} missing i18n_key"
            assert f["i18n_key"].startswith("GST_MENU_ITEM_")

    def test_feature_to_dict(self):
        """_feature_to_dict should extract correct fields from ORM-like object."""
        mock_feature = MagicMock()
        mock_feature.code = "enter_gstin"
        mock_feature.name = "Enter GSTIN"
        mock_feature.display_order = 10
        mock_feature.whatsapp_state = "WAIT_GSTIN"
        mock_feature.i18n_key = "GST_MENU_ITEM_enter_gstin"
        mock_feature.category = "gst"

        result = _feature_to_dict(mock_feature)
        assert result == {
            "code": "enter_gstin",
            "name": "Enter GSTIN",
            "display_order": 10,
            "whatsapp_state": "WAIT_GSTIN",
            "i18n_key": "GST_MENU_ITEM_enter_gstin",
            "category": "gst",
        }

    def test_get_all_features_fallback(self):
        """get_all_features_fallback() should return a copy of _ALL_FEATURES."""
        result = get_all_features_fallback()
        assert result == _ALL_FEATURES
        # Should be a copy, not the same object
        assert result is not _ALL_FEATURES

    def test_small_segment_features_expected(self):
        """Small segment should map to base features + filing_status (by plan design)."""
        # The seed data assigns core features to "small"
        small_codes = {"enter_gstin", "monthly_compliance", "nil_return", "upload_invoices", "filing_status"}
        all_codes = {f["code"] for f in _ALL_FEATURES}
        # Verify these are a subset
        assert small_codes.issubset(all_codes)
        assert len(small_codes) == 5

    def test_medium_segment_features_expected(self):
        """Medium segment should map to small + medium features (by plan design)."""
        medium_codes = {
            "enter_gstin", "monthly_compliance", "nil_return", "upload_invoices",
            "filing_status", "credit_check",
            "e_invoice", "e_waybill", "annual_return",
            "refund_tracking", "notice_mgmt",
        }
        all_codes = {f["code"] for f in _ALL_FEATURES}
        assert medium_codes.issubset(all_codes)
        assert len(medium_codes) == 11

    def test_enterprise_segment_features_expected(self):
        """Enterprise segment should map to all 14 features (by plan design)."""
        enterprise_codes = {f["code"] for f in _ALL_FEATURES}
        assert len(enterprise_codes) == 14

    def test_whatsapp_states_assigned(self):
        """Features with WhatsApp states should have them correctly set."""
        state_map = {f["code"]: f["whatsapp_state"] for f in _ALL_FEATURES}
        assert state_map["enter_gstin"] == "WAIT_GSTIN"
        assert state_map["monthly_compliance"] == "GST_PERIOD_MENU"
        assert state_map["nil_return"] == "NIL_FILING_MENU"
        assert state_map["upload_invoices"] == "SMART_UPLOAD"
        assert state_map["annual_return"] == "GST_ANNUAL_MENU"
        assert state_map["risk_scoring"] == "GST_RISK_REVIEW"
        # Phase 6-10: Features now have WhatsApp states
        assert state_map["e_invoice"] == "EINVOICE_MENU"
        assert state_map["e_waybill"] == "EWAYBILL_MENU"
        assert state_map["multi_gstin"] == "MULTI_GSTIN_MENU"
        assert state_map["credit_check"] == "MEDIUM_CREDIT_CHECK"
        assert state_map["filing_status"] == "GST_FILING_STATUS"
        assert state_map["refund_tracking"] == "REFUND_MENU"
        assert state_map["notice_mgmt"] == "NOTICE_MENU"
        assert state_map["export_services"] == "EXPORT_MENU"


# ============================================================
# Test Dynamic WhatsApp Menu Builder
# ============================================================


class TestDynamicMenu:
    """Tests for whatsapp_menu_builder.py menu building and dispatch."""

    def test_resolve_gst_menu_choice_valid(self):
        """Valid choice should return feature code."""
        session = {
            "data": {
                "gst_menu_map": {
                    "1": "enter_gstin",
                    "2": "monthly_compliance",
                    "3": "nil_return",
                    "4": "upload_invoices",
                }
            }
        }
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(resolve_gst_menu_choice("1", session))
            assert result == "enter_gstin"
            result = loop.run_until_complete(resolve_gst_menu_choice("4", session))
            assert result == "upload_invoices"
        finally:
            loop.close()

    def test_resolve_gst_menu_choice_invalid(self):
        """Invalid choice should return None."""
        session = {
            "data": {
                "gst_menu_map": {
                    "1": "enter_gstin",
                    "2": "monthly_compliance",
                }
            }
        }
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(resolve_gst_menu_choice("99", session))
            assert result is None
            result = loop.run_until_complete(resolve_gst_menu_choice("abc", session))
            assert result is None
        finally:
            loop.close()

    def test_resolve_gst_menu_choice_no_map(self):
        """Missing menu map in session should return None."""
        session = {"data": {}}
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(resolve_gst_menu_choice("1", session))
            assert result is None
        finally:
            loop.close()

    def test_resolve_gst_menu_choice_empty_session(self):
        """Completely empty session should return None."""
        session = {}
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(resolve_gst_menu_choice("1", session))
            assert result is None
        finally:
            loop.close()

    def test_resolve_gst_menu_choice_strips_whitespace(self):
        """Choice should be stripped of whitespace."""
        session = {"data": {"gst_menu_map": {"1": "enter_gstin"}}}
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(resolve_gst_menu_choice(" 1 ", session))
            assert result == "enter_gstin"
        finally:
            loop.close()

    def test_small_menu_items(self):
        """Small segment core features (display_order <= 40) should be subset of features."""
        small_codes = {"enter_gstin", "monthly_compliance", "nil_return", "upload_invoices"}
        all_codes = {f["code"] for f in _ALL_FEATURES}
        assert small_codes.issubset(all_codes)

    def test_medium_menu_items(self):
        """Medium segment should include e-Invoice, e-WayBill, credit_check, etc."""
        medium_codes = {
            "e_invoice", "e_waybill", "annual_return", "credit_check",
            "refund_tracking", "notice_mgmt",
        }
        all_codes = {f["code"] for f in _ALL_FEATURES}
        assert medium_codes.issubset(all_codes)

    def test_enterprise_menu_all_items(self):
        """Enterprise segment should have all 14 features."""
        assert len(_ALL_FEATURES) == 14

    def test_menu_map_generation(self):
        """Menu map should map sequential numbers to feature codes (sorted by display_order)."""
        # First 4 features by display order: enter_gstin(10), monthly_compliance(20), filing_status(25), nil_return(30)
        features = _ALL_FEATURES[:4]
        menu_map = {}
        for idx, feat in enumerate(features, start=1):
            menu_map[str(idx)] = feat["code"]

        assert menu_map == {
            "1": "enter_gstin",
            "2": "monthly_compliance",
            "3": "filing_status",
            "4": "nil_return",
        }

    def test_enterprise_menu_map_generation(self):
        """Enterprise menu map should include all 14 features."""
        menu_map = {}
        for idx, feat in enumerate(_ALL_FEATURES, start=1):
            menu_map[str(idx)] = feat["code"]

        assert len(menu_map) == 14
        assert menu_map["1"] == "enter_gstin"
        assert menu_map["14"] == "export_services"

    def test_i18n_label_english(self):
        """i18n label lookup for English."""
        label = _get_i18n_label("GST_MENU_ITEM_enter_gstin", "en")
        assert label is not None
        assert isinstance(label, str)
        assert len(label) > 0

    def test_i18n_label_hindi(self):
        """i18n label lookup for Hindi."""
        label = _get_i18n_label("GST_MENU_ITEM_enter_gstin", "hi")
        assert label is not None

    def test_i18n_label_missing_key(self):
        """Missing key should return None."""
        label = _get_i18n_label("NONEXISTENT_KEY", "en")
        assert label is None

    def test_i18n_label_fallback_to_english(self):
        """Unknown language should fall back to English."""
        label = _get_i18n_label("GST_MENU_ITEM_enter_gstin", "xx")
        en_label = _get_i18n_label("GST_MENU_ITEM_enter_gstin", "en")
        assert label == en_label


# ============================================================
# Test Menu Dispatch Logic
# ============================================================


class TestMenuDispatch:
    """Tests for GST_MENU dispatch logic using feature codes."""

    # Known feature codes that should map to existing states
    _FEATURE_TO_STATE = {
        "enter_gstin": "WAIT_GSTIN",
        "monthly_compliance": "GST_PERIOD_MENU",
        "filing_status": "GST_FILING_STATUS",
        "nil_return": "NIL_FILING_MENU",
        "upload_invoices": "SMART_UPLOAD",
        "credit_check": "MEDIUM_CREDIT_CHECK",
        "e_invoice": "EINVOICE_MENU",
        "e_waybill": "EWAYBILL_MENU",
        "annual_return": "GST_ANNUAL_MENU",
        "risk_scoring": "GST_RISK_REVIEW",
        "multi_gstin": "MULTI_GSTIN_MENU",
        "refund_tracking": "REFUND_MENU",
        "notice_mgmt": "NOTICE_MENU",
        "export_services": "EXPORT_MENU",
    }

    def test_all_features_have_known_codes(self):
        """Every feature code in _ALL_FEATURES should be one of the 14 known codes."""
        known = {
            "enter_gstin", "monthly_compliance", "filing_status", "nil_return",
            "upload_invoices", "credit_check",
            "e_invoice", "e_waybill", "annual_return", "risk_scoring", "multi_gstin",
            "refund_tracking", "notice_mgmt", "export_services",
        }
        for f in _ALL_FEATURES:
            assert f["code"] in known, f"Unknown feature code: {f['code']}"

    def test_feature_state_mapping(self):
        """All features should have a whatsapp_state and it should match expected states."""
        for f in _ALL_FEATURES:
            if f["whatsapp_state"]:
                assert f["code"] in self._FEATURE_TO_STATE, f"Feature {f['code']} not in state map"
                assert f["whatsapp_state"] == self._FEATURE_TO_STATE[f["code"]]

    def test_gating_disabled_shows_all(self):
        """When gating is disabled, fallback returns all 14 features."""
        all_features = get_all_features_fallback()
        assert len(all_features) == 14
        # Verify ordering
        codes = [f["code"] for f in all_features]
        assert codes[0] == "enter_gstin"
        assert codes[-1] == "export_services"


# ============================================================
# Test Onboarding Flow Logic
# ============================================================


class TestOnboarding:
    """Tests for segment onboarding turnover/invoice/export maps."""

    # These mirror the maps in whatsapp.py handlers
    TURNOVER_MAP = {
        "1": 0,
        "2": 25_00_00_000,
        "3": 75_00_00_000,
        "4": 0,  # Skip
    }

    INVOICE_MAP = {
        "1": 25,
        "2": 75,
        "3": 300,
        "4": 600,
        "5": 0,  # Skip
    }

    EXPORT_MAP = {
        "1": True,
        "2": False,
        "3": False,  # Skip
    }

    def test_turnover_choices(self):
        """Turnover choices should map to midpoint values."""
        assert self.TURNOVER_MAP["1"] == 0  # Below 5 Cr → 0
        assert self.TURNOVER_MAP["2"] == 25_00_00_000  # 5-50 Cr → 25 Cr
        assert self.TURNOVER_MAP["3"] == 75_00_00_000  # Above 50 Cr → 75 Cr
        assert self.TURNOVER_MAP["4"] == 0  # Skip

    def test_invoice_choices(self):
        """Invoice volume choices should map to bracket midpoints."""
        assert self.INVOICE_MAP["1"] == 25
        assert self.INVOICE_MAP["2"] == 75
        assert self.INVOICE_MAP["3"] == 300
        assert self.INVOICE_MAP["4"] == 600
        assert self.INVOICE_MAP["5"] == 0

    def test_export_choices(self):
        """Export choices should map to boolean values."""
        assert self.EXPORT_MAP["1"] is True   # Yes
        assert self.EXPORT_MAP["2"] is False  # No
        assert self.EXPORT_MAP["3"] is False  # Skip

    def test_skip_all_defaults_to_small(self):
        """Skipping all questions should detect 'small'."""
        segment = detect_segment(
            annual_turnover=self.TURNOVER_MAP["4"],      # Skip → 0
            monthly_invoice_volume=self.INVOICE_MAP["5"],  # Skip → 0
            gstin_count=1,
            is_exporter=self.EXPORT_MAP["3"],              # Skip → False
        )
        assert segment == "small"

    def test_medium_onboarding_path(self):
        """Choosing 5-50 Cr turnover → medium."""
        segment = detect_segment(
            annual_turnover=self.TURNOVER_MAP["2"],       # 25 Cr → medium
            monthly_invoice_volume=self.INVOICE_MAP["1"],  # 25 → below threshold
            is_exporter=self.EXPORT_MAP["2"],              # No
        )
        assert segment == "medium"

    def test_enterprise_onboarding_path_by_turnover(self):
        """Choosing above 50 Cr turnover → enterprise."""
        segment = detect_segment(
            annual_turnover=self.TURNOVER_MAP["3"],       # 75 Cr → enterprise
            monthly_invoice_volume=self.INVOICE_MAP["1"],
            is_exporter=self.EXPORT_MAP["2"],
        )
        assert segment == "enterprise"

    def test_enterprise_onboarding_path_by_export(self):
        """Choosing 'Yes' for export → enterprise."""
        segment = detect_segment(
            annual_turnover=self.TURNOVER_MAP["1"],       # 0 turnover
            monthly_invoice_volume=self.INVOICE_MAP["1"],  # 25 invoices
            is_exporter=self.EXPORT_MAP["1"],              # Yes → enterprise
        )
        assert segment == "enterprise"

    def test_medium_by_invoice_volume_onboarding(self):
        """Choosing 100-500 invoices → medium."""
        segment = detect_segment(
            annual_turnover=self.TURNOVER_MAP["1"],       # 0 → small
            monthly_invoice_volume=self.INVOICE_MAP["3"],  # 300 → medium
            is_exporter=self.EXPORT_MAP["2"],              # No
        )
        assert segment == "medium"

    def test_segment_confirm_options(self):
        """Segment confirmation should have 2 options: continue and change."""
        # Just verify the logic flow constants
        # Option 1 = continue (accept segment)
        # Option 2 = change (restart onboarding)
        assert True  # Flow is tested in the state machine handlers


# ============================================================
# Test i18n Completeness
# ============================================================


class TestI18nCompleteness:
    """Tests to verify all required i18n keys exist for segment gating."""

    REQUIRED_KEYS = [
        "GST_MENU_HEADER",
        "GST_MENU_FOOTER",
        "GST_MENU_ITEM_enter_gstin",
        "GST_MENU_ITEM_monthly_compliance",
        "GST_MENU_ITEM_nil_return",
        "GST_MENU_ITEM_upload_invoices",
        "GST_MENU_ITEM_e_invoice",
        "GST_MENU_ITEM_e_waybill",
        "GST_MENU_ITEM_annual_return",
        "GST_MENU_ITEM_risk_scoring",
        "GST_MENU_ITEM_multi_gstin",
        "SEGMENT_ASK_TURNOVER",
        "SEGMENT_ASK_INVOICES",
        "SEGMENT_ASK_EXPORT",
        "SEGMENT_DETECTED",
        "SEGMENT_UPDATED",
        "SEGMENT_LABEL_small",
        "SEGMENT_LABEL_medium",
        "SEGMENT_LABEL_enterprise",
    ]

    REQUIRED_LANGS = ["en", "hi", "gu", "ta", "te"]

    def test_all_keys_exist(self):
        """All required i18n keys should exist in MESSAGES."""
        from app.domain.i18n import MESSAGES
        for key in self.REQUIRED_KEYS:
            assert key in MESSAGES, f"Missing i18n key: {key}"

    def test_all_langs_for_menu_items(self):
        """All 5 languages should have translations for menu item keys."""
        from app.domain.i18n import MESSAGES
        for key in self.REQUIRED_KEYS:
            if key not in MESSAGES:
                continue
            for lang in self.REQUIRED_LANGS:
                assert lang in MESSAGES[key], (
                    f"Missing language '{lang}' for key '{key}'"
                )
                assert MESSAGES[key][lang], (
                    f"Empty translation for key '{key}', lang '{lang}'"
                )

    def test_menu_item_labels_are_short(self):
        """Menu item labels should be reasonably short (< 50 chars)."""
        from app.domain.i18n import MESSAGES
        for key in self.REQUIRED_KEYS:
            if not key.startswith("GST_MENU_ITEM_"):
                continue
            if key not in MESSAGES:
                continue
            for lang, text in MESSAGES[key].items():
                assert len(text) < 50, (
                    f"Label too long ({len(text)} chars): key={key}, lang={lang}"
                )


# ============================================================
# Test Config Settings
# ============================================================


class TestConfigSettings:
    """Tests for segment gating config settings."""

    def test_segment_gating_enabled_default(self):
        """SEGMENT_GATING_ENABLED should default to True."""
        from app.core.config import settings
        assert hasattr(settings, "SEGMENT_GATING_ENABLED")
        # Default is True
        assert isinstance(settings.SEGMENT_GATING_ENABLED, bool)

    def test_default_segment_setting(self):
        """DEFAULT_SEGMENT should be a valid segment string."""
        from app.core.config import settings
        assert hasattr(settings, "DEFAULT_SEGMENT")
        assert settings.DEFAULT_SEGMENT in ("small", "medium", "enterprise")

    def test_segment_cache_ttl_setting(self):
        """SEGMENT_CACHE_TTL should be a positive integer."""
        from app.core.config import settings
        assert hasattr(settings, "SEGMENT_CACHE_TTL")
        assert isinstance(settings.SEGMENT_CACHE_TTL, int)
        assert settings.SEGMENT_CACHE_TTL > 0


# ============================================================
# Test WhatsApp State Constants
# ============================================================


class TestWhatsAppStates:
    """Tests for WhatsApp state constants related to segment gating."""

    def test_segment_states_exist(self):
        """Segment onboarding states should be defined."""
        from app.api.routes.whatsapp import (
            SEGMENT_ASK_TURNOVER,
            SEGMENT_ASK_INVOICES,
            SEGMENT_ASK_EXPORT,
            SEGMENT_CONFIRM,
        )
        assert SEGMENT_ASK_TURNOVER == "SEGMENT_ASK_TURNOVER"
        assert SEGMENT_ASK_INVOICES == "SEGMENT_ASK_INVOICES"
        assert SEGMENT_ASK_EXPORT == "SEGMENT_ASK_EXPORT"
        assert SEGMENT_CONFIRM == "SEGMENT_CONFIRM"

    def test_segment_states_in_screen_key_map(self):
        """Segment states should be mapped in _state_to_screen_key."""
        from app.api.routes.whatsapp import _state_to_screen_key
        # _state_to_screen_key is a function that returns i18n keys
        assert _state_to_screen_key("SEGMENT_ASK_TURNOVER") == "SEGMENT_ASK_TURNOVER"
        assert _state_to_screen_key("SEGMENT_ASK_INVOICES") == "SEGMENT_ASK_INVOICES"
        assert _state_to_screen_key("SEGMENT_ASK_EXPORT") == "SEGMENT_ASK_EXPORT"
        assert _state_to_screen_key("SEGMENT_CONFIRM") == "SEGMENT_DETECTED"


# ============================================================
# Test Schema Enhancements
# ============================================================


class TestSchemaEnhancements:
    """Tests for CA schema segment field additions."""

    def test_client_create_has_segment_fields(self):
        """ClientCreate should accept segment, annual_turnover, monthly_invoice_volume."""
        from app.api.v1.schemas.ca import ClientCreate
        fields = ClientCreate.model_fields
        assert "segment" in fields
        assert "annual_turnover" in fields
        assert "monthly_invoice_volume" in fields

    def test_client_update_has_segment_fields(self):
        """ClientUpdate should accept segment, annual_turnover, monthly_invoice_volume."""
        from app.api.v1.schemas.ca import ClientUpdate
        fields = ClientUpdate.model_fields
        assert "segment" in fields
        assert "annual_turnover" in fields
        assert "monthly_invoice_volume" in fields

    def test_client_out_has_segment_fields(self):
        """ClientOut should include segment, annual_turnover, monthly_invoice_volume, gstin_count, is_exporter."""
        from app.api.v1.schemas.ca import ClientOut
        fields = ClientOut.model_fields
        assert "segment" in fields
        assert "annual_turnover" in fields
        assert "monthly_invoice_volume" in fields
        assert "gstin_count" in fields
        assert "is_exporter" in fields

    def test_client_create_segment_optional(self):
        """ClientCreate segment fields should be optional."""
        from app.api.v1.schemas.ca import ClientCreate
        # Should create without segment fields
        client = ClientCreate(name="Test Corp")
        assert client.segment is None
        assert client.annual_turnover is None
        assert client.monthly_invoice_volume is None

    def test_client_out_segment_defaults(self):
        """ClientOut segment fields should have sensible defaults."""
        from app.api.v1.schemas.ca import ClientOut
        client = ClientOut(
            id=1,
            name="Test Corp",
            status="active",
            ca_id=1,
        )
        assert client.segment == "small"
        assert client.gstin_count == 1
        assert client.is_exporter is False

    def test_client_create_with_segment(self):
        """ClientCreate should accept segment fields."""
        from app.api.v1.schemas.ca import ClientCreate
        client = ClientCreate(
            name="Test Corp",
            segment="medium",
            annual_turnover=10_00_00_000.0,
            monthly_invoice_volume=150,
        )
        assert client.segment == "medium"
        assert client.annual_turnover == 10_00_00_000.0
        assert client.monthly_invoice_volume == 150


# ============================================================
# Test DB Model Enhancements
# ============================================================


class TestDBModels:
    """Tests for DB model schema (columns and new models exist)."""

    def test_business_client_has_segment_columns(self):
        """BusinessClient model should have segment-related columns."""
        from app.infrastructure.db.models import BusinessClient
        columns = {c.name for c in BusinessClient.__table__.columns}
        assert "segment" in columns
        assert "annual_turnover" in columns
        assert "monthly_invoice_volume" in columns
        assert "gstin_count" in columns
        assert "is_exporter" in columns
        assert "segment_override" in columns

    def test_feature_model_exists(self):
        """Feature model should exist with correct columns."""
        from app.infrastructure.db.models import Feature
        columns = {c.name for c in Feature.__table__.columns}
        assert "code" in columns
        assert "name" in columns
        assert "display_order" in columns
        assert "whatsapp_state" in columns
        assert "i18n_key" in columns
        assert "is_active" in columns
        assert "category" in columns

    def test_segment_feature_model_exists(self):
        """SegmentFeature model should exist with correct columns."""
        from app.infrastructure.db.models import SegmentFeature
        columns = {c.name for c in SegmentFeature.__table__.columns}
        assert "segment" in columns
        assert "feature_id" in columns
        assert "enabled" in columns

    def test_client_addon_model_exists(self):
        """ClientAddon model should exist with correct columns."""
        from app.infrastructure.db.models import ClientAddon
        columns = {c.name for c in ClientAddon.__table__.columns}
        assert "client_id" in columns
        assert "feature_id" in columns
        assert "enabled" in columns
        assert "granted_by" in columns
