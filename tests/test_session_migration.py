# tests/test_session_migration.py
"""Tests for session cache v1→v2 migration, soft/hard expiry, and touch logic."""

import time
from unittest.mock import patch

import pytest

from app.infrastructure.cache.session_cache import (
    SESSION_VERSION,
    SESSION_TTL_SECONDS,
    SOFT_EXPIRY_SECONDS,
    SENSITIVE_TIMEOUT_SECONDS,
    _default_session,
    _migrate_session,
    is_soft_expired,
    is_sensitive_expired,
    touch_session,
)


# ── _default_session ──────────────────────────────────────────────────

class TestDefaultSession:
    def test_returns_fresh_dict(self):
        s1 = _default_session()
        s2 = _default_session()
        assert s1 is not s2, "Each call should return a new dict"

    def test_has_version_2(self):
        s = _default_session()
        assert s["version"] == 2

    def test_has_choose_lang_state(self):
        s = _default_session()
        assert s["state"] == "CHOOSE_LANG"

    def test_has_default_lang(self):
        s = _default_session()
        assert s["lang"] == "en"

    def test_has_empty_stack(self):
        s = _default_session()
        assert s["stack"] == []

    def test_has_empty_data(self):
        s = _default_session()
        assert s["data"] == {}

    def test_has_last_active_ts(self):
        before = time.time()
        s = _default_session()
        after = time.time()
        assert before <= s["last_active_ts"] <= after


# ── _migrate_session ──────────────────────────────────────────────────

class TestMigrateSession:
    def test_v1_session_gets_version_field(self):
        """A v1 session (no version key) should be upgraded to v2."""
        v1 = {"state": "MAIN_MENU", "lang": "hi", "data": {"gstin": "ABC"}}
        result = _migrate_session(v1)
        assert result["version"] == SESSION_VERSION
        assert result is v1, "Should mutate in place"

    def test_v1_session_gets_last_active_ts(self):
        v1 = {"state": "MAIN_MENU", "lang": "en", "data": {}}
        before = time.time()
        _migrate_session(v1)
        after = time.time()
        assert "last_active_ts" in v1
        assert before <= v1["last_active_ts"] <= after

    def test_v1_preserves_existing_fields(self):
        v1 = {
            "state": "GST_MENU",
            "lang": "gu",
            "data": {"gstin": "29ABCDE1234F1Z5", "invoices": [1, 2, 3]},
            "stack": ["MAIN_MENU"],
        }
        result = _migrate_session(v1)
        assert result["state"] == "GST_MENU"
        assert result["lang"] == "gu"
        assert result["data"]["gstin"] == "29ABCDE1234F1Z5"
        assert result["stack"] == ["MAIN_MENU"]

    def test_v2_session_not_modified(self):
        """A session already at v2 should pass through unchanged."""
        v2 = {
            "version": 2,
            "state": "GST_MENU",
            "lang": "en",
            "data": {},
            "last_active_ts": 1000.0,
        }
        result = _migrate_session(v2)
        assert result["last_active_ts"] == 1000.0, "Should NOT overwrite existing ts"

    def test_explicit_v1_tag_gets_migrated(self):
        """A session with version=1 explicitly set should be upgraded."""
        v1 = {"version": 1, "state": "MAIN_MENU", "lang": "en", "data": {}}
        result = _migrate_session(v1)
        assert result["version"] == SESSION_VERSION

    def test_future_version_not_downgraded(self):
        """A session with version > current should not be touched."""
        future = {
            "version": 99,
            "state": "MAIN_MENU",
            "lang": "en",
            "data": {},
            "last_active_ts": 5000.0,
        }
        result = _migrate_session(future)
        assert result["version"] == 99
        assert result["last_active_ts"] == 5000.0

    def test_v1_with_existing_last_active_ts_not_overwritten(self):
        """If v1 somehow already has last_active_ts, keep it."""
        v1 = {"state": "MAIN_MENU", "lang": "en", "data": {}, "last_active_ts": 42.0}
        _migrate_session(v1)
        assert v1["last_active_ts"] == 42.0


# ── is_soft_expired ───────────────────────────────────────────────────

class TestSoftExpiry:
    def test_fresh_session_not_expired(self):
        s = _default_session()
        assert is_soft_expired(s) is False

    def test_old_session_is_expired(self):
        s = _default_session()
        s["last_active_ts"] = time.time() - SOFT_EXPIRY_SECONDS - 1
        assert is_soft_expired(s) is True

    def test_session_at_boundary_not_expired(self):
        s = _default_session()
        # Exactly at boundary — time.time() - ts == SOFT_EXPIRY_SECONDS → NOT > threshold
        s["last_active_ts"] = time.time() - SOFT_EXPIRY_SECONDS + 1
        assert is_soft_expired(s) is False

    def test_missing_last_active_ts_treated_as_expired(self):
        s = {"state": "MAIN_MENU", "data": {}}
        assert is_soft_expired(s) is True

    def test_soft_expiry_is_30_minutes(self):
        assert SOFT_EXPIRY_SECONDS == 30 * 60


# ── is_sensitive_expired ──────────────────────────────────────────────

class TestSensitiveExpiry:
    def test_fresh_session_not_expired(self):
        s = _default_session()
        assert is_sensitive_expired(s) is False

    def test_session_past_10_min_is_expired(self):
        s = _default_session()
        s["last_active_ts"] = time.time() - SENSITIVE_TIMEOUT_SECONDS - 1
        assert is_sensitive_expired(s) is True

    def test_sensitive_timeout_is_10_minutes(self):
        assert SENSITIVE_TIMEOUT_SECONDS == 10 * 60


# ── touch_session ─────────────────────────────────────────────────────

class TestTouchSession:
    def test_updates_last_active_ts(self):
        s = _default_session()
        s["last_active_ts"] = 0  # pretend stale
        before = time.time()
        touch_session(s)
        after = time.time()
        assert before <= s["last_active_ts"] <= after

    def test_touch_resets_soft_expiry(self):
        s = _default_session()
        s["last_active_ts"] = time.time() - SOFT_EXPIRY_SECONDS - 100
        assert is_soft_expired(s) is True
        touch_session(s)
        assert is_soft_expired(s) is False


# ── Constants ─────────────────────────────────────────────────────────

class TestConstants:
    def test_session_version_is_2(self):
        assert SESSION_VERSION == 2

    def test_session_ttl_is_14_days(self):
        assert SESSION_TTL_SECONDS == 14 * 24 * 60 * 60

    def test_soft_expiry_is_30_min(self):
        assert SOFT_EXPIRY_SECONDS == 30 * 60

    def test_sensitive_timeout_is_10_min(self):
        assert SENSITIVE_TIMEOUT_SECONDS == 10 * 60
