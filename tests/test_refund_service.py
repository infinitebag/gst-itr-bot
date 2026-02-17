# tests/test_refund_service.py
"""Tests for refund service (Phase 9A)."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_create_refund_claim(event_loop):
    """create_refund_claim should insert a RefundClaim and return success."""
    from app.domain.services.refund_service import create_refund_claim

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    # Patch the model so we don't need real DB
    with patch("app.infrastructure.db.models.RefundClaim") as MockModel:
        mock_instance = MagicMock()
        mock_instance.id = 42
        mock_instance.status = "draft"
        MockModel.return_value = mock_instance

        result = event_loop.run_until_complete(
            create_refund_claim("36AABCU9603R1ZM", 1, "excess_balance", 50000.0, "2025-01", mock_db)
        )
        assert result["success"] is True
        assert result["status"] == "draft"


def test_list_refund_claims_empty(event_loop):
    """list_refund_claims returns empty list when no claims exist."""
    from app.domain.services.refund_service import list_refund_claims

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = event_loop.run_until_complete(
        list_refund_claims("36AABCU9603R1ZM", mock_db)
    )
    assert result == []


def test_list_refund_claims_with_data(event_loop):
    """list_refund_claims returns formatted claim data."""
    from app.domain.services.refund_service import list_refund_claims

    mock_claim = MagicMock()
    mock_claim.id = 1
    mock_claim.gstin = "36AABCU9603R1ZM"
    mock_claim.claim_type = "excess_balance"
    mock_claim.amount = 50000.0
    mock_claim.period = "2025-01"
    mock_claim.status = "draft"
    mock_claim.arn = None

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_claim]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = event_loop.run_until_complete(
        list_refund_claims("36AABCU9603R1ZM", mock_db)
    )
    assert len(result) == 1
    assert result[0]["claim_type"] == "excess_balance"
    assert result[0]["amount"] == 50000.0


def test_get_refund_status_found(event_loop):
    """get_refund_status returns claim dict when found."""
    from app.domain.services.refund_service import get_refund_status

    mock_claim = MagicMock()
    mock_claim.id = 1
    mock_claim.gstin = "36AABCU9603R1ZM"
    mock_claim.claim_type = "export"
    mock_claim.amount = 25000.0
    mock_claim.period = "2025-02"
    mock_claim.status = "submitted"
    mock_claim.arn = "ARN123"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_claim
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = event_loop.run_until_complete(
        get_refund_status(1, mock_db)
    )
    assert result is not None
    assert result["status"] == "submitted"
    assert result["arn"] == "ARN123"


def test_get_refund_status_not_found(event_loop):
    """get_refund_status returns None when claim doesn't exist."""
    from app.domain.services.refund_service import get_refund_status

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = event_loop.run_until_complete(
        get_refund_status(999, mock_db)
    )
    assert result is None
