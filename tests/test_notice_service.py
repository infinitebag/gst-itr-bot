# tests/test_notice_service.py
"""Tests for notice service (Phase 9B)."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_create_notice_success(event_loop):
    """create_notice should insert a GSTNotice and return success."""
    from app.domain.services.notice_service import create_notice

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    with patch("app.infrastructure.db.models.GSTNotice") as MockModel:
        mock_instance = MagicMock()
        mock_instance.id = 10
        mock_instance.status = "received"
        MockModel.return_value = mock_instance

        result = event_loop.run_until_complete(
            create_notice(
                gstin="36AABCU9603R1ZM",
                user_id=1,
                notice_type="ASMT-10",
                description="Assessment notice for Jan 2025",
                due_date="15-03-2025",
                db=mock_db,
            )
        )
        assert result["success"] is True


def test_create_notice_with_invalid_date(event_loop):
    """create_notice should handle invalid date gracefully (set due_date=None)."""
    from app.domain.services.notice_service import create_notice

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    with patch("app.infrastructure.db.models.GSTNotice") as MockModel:
        mock_instance = MagicMock()
        mock_instance.id = 11
        mock_instance.status = "received"
        MockModel.return_value = mock_instance

        result = event_loop.run_until_complete(
            create_notice(
                gstin="36AABCU9603R1ZM",
                user_id=1,
                notice_type="DRC-01",
                description="Demand notice",
                due_date="invalid-date",
                db=mock_db,
            )
        )
        assert result["success"] is True


def test_list_pending_notices_empty(event_loop):
    """list_pending_notices returns empty when no notices."""
    from app.domain.services.notice_service import list_pending_notices

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = event_loop.run_until_complete(
        list_pending_notices("36AABCU9603R1ZM", mock_db)
    )
    assert result == []


def test_list_pending_notices_with_data(event_loop):
    """list_pending_notices formats notice data correctly."""
    from app.domain.services.notice_service import list_pending_notices

    mock_notice = MagicMock()
    mock_notice.id = 10
    mock_notice.notice_type = "ASMT-10"
    mock_notice.description = "Assessment notice"
    mock_notice.due_date = date(2025, 3, 15)
    mock_notice.status = "received"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_notice]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = event_loop.run_until_complete(
        list_pending_notices("36AABCU9603R1ZM", mock_db)
    )
    assert len(result) == 1
    assert result[0]["notice_type"] == "ASMT-10"
    assert result[0]["due_date"] == "2025-03-15"


def test_update_notice_status_success(event_loop):
    """update_notice_status should update status and response."""
    from app.domain.services.notice_service import update_notice_status

    mock_notice = MagicMock()
    mock_notice.id = 10
    mock_notice.status = "received"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_notice
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    result = event_loop.run_until_complete(
        update_notice_status(10, "acknowledged", "We have received this notice.", mock_db)
    )
    assert result is True
    assert mock_notice.status == "acknowledged"


def test_update_notice_status_not_found(event_loop):
    """update_notice_status should return False when notice not found."""
    from app.domain.services.notice_service import update_notice_status

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = event_loop.run_until_complete(
        update_notice_status(999, "acknowledged", "", mock_db)
    )
    assert result is False
