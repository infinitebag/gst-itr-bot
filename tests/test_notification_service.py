# tests/test_notification_service.py
"""Tests for notification service (Phase 10)."""

import pytest
from app.core.config import settings


def test_notification_settings_exist():
    assert hasattr(settings, "NOTIFICATION_ENABLED")
    assert hasattr(settings, "NOTIFICATION_CHECK_INTERVAL_SECONDS")
    assert hasattr(settings, "NOTIFICATION_REMINDER_DAYS")
    assert hasattr(settings, "NOTIFICATION_DAILY_SCHEDULE_HOUR")


def test_notification_defaults():
    assert settings.NOTIFICATION_ENABLED is True
    assert settings.NOTIFICATION_CHECK_INTERVAL_SECONDS == 3600
    assert settings.NOTIFICATION_REMINDER_DAYS == [7, 3, 1]
    assert settings.NOTIFICATION_DAILY_SCHEDULE_HOUR == 9
