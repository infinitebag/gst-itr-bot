# tests/test_ewaybill_flow.py
"""Tests for e-WayBill flow service (Phase 6B)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.services.ewaybill_flow import (
    prepare_ewb_payload,
    generate_ewb,
    track_ewb,
    update_vehicle,
    TRANSPORT_MODES,
)

# Deferred import — patch at the source module
_EWAYBILL_CLIENT_PATH = "app.infrastructure.external.ewaybill_client.EWayBillClient"


def test_prepare_ewb_payload(event_loop):
    invoice = {
        "invoice_number": "INV-001",
        "invoice_date": "2025-01-15",
        "receiver_gstin": "29AAECC1206D1ZM",
        "total_amount": 55000,
        "taxable_value": 46610,
    }
    transport = {"vehicle_no": "KA01AB1234", "trans_mode": "1", "distance": "150"}
    payload = event_loop.run_until_complete(
        prepare_ewb_payload(invoice, "36AABCU9603R1ZM", transport)
    )
    assert payload["docNo"] == "INV-001"
    assert payload["fromGstin"] == "36AABCU9603R1ZM"
    assert payload["vehicleNo"] == "KA01AB1234"
    assert payload["transDistance"] == "150"
    assert payload["transMode"] == "1"


def test_generate_ewb_not_configured(event_loop):
    with patch(_EWAYBILL_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = False
        result = event_loop.run_until_complete(
            generate_ewb("36AABCU9603R1ZM", {}, {})
        )
        assert result["success"] is False
        assert "not configured" in result["error"]


def test_generate_ewb_success(event_loop):
    with patch(_EWAYBILL_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.return_value = "token"
        mock_client.generate_ewaybill.return_value = {
            "data": {
                "ewayBillNo": "EWB123",
                "validUpto": "2025-02-15",
                "ewayBillDate": "2025-01-15",
            }
        }
        transport = {"vehicle_no": "KA01AB1234", "trans_mode": "1", "distance": "100"}
        result = event_loop.run_until_complete(
            generate_ewb("36AABCU9603R1ZM", {"invoice_number": "X"}, transport)
        )
        assert result["success"] is True
        assert result["ewb_no"] == "EWB123"


def test_track_ewb_not_configured(event_loop):
    with patch(_EWAYBILL_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = False
        result = event_loop.run_until_complete(
            track_ewb("36AABCU9603R1ZM", "EWB123")
        )
        assert result["success"] is False


def test_track_ewb_success(event_loop):
    with patch(_EWAYBILL_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.return_value = "token"
        mock_client.get_ewaybill.return_value = {
            "data": {"status": "Active", "validUpto": "2025-02-15"}
        }
        result = event_loop.run_until_complete(
            track_ewb("36AABCU9603R1ZM", "EWB123")
        )
        assert result["success"] is True
        assert result["status"] == "Active"


def test_update_vehicle_success(event_loop):
    with patch(_EWAYBILL_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.return_value = "token"
        mock_client.update_vehicle.return_value = {"status": "ok"}
        result = event_loop.run_until_complete(
            update_vehicle("36AABCU9603R1ZM", "EWB123", "KA02CD5678", "Breakdown")
        )
        assert result["success"] is True


def test_update_vehicle_not_configured(event_loop):
    with patch(_EWAYBILL_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = False
        result = event_loop.run_until_complete(
            update_vehicle("36AABCU9603R1ZM", "EWB123", "KA02CD5678", "Breakdown")
        )
        assert result["success"] is False


def test_transport_modes():
    """TRANSPORT_MODES maps digit strings to (code, label) tuples."""
    assert "1" in TRANSPORT_MODES
    assert "2" in TRANSPORT_MODES
    assert TRANSPORT_MODES["1"][1] == "Road"
    assert TRANSPORT_MODES["2"][1] == "Rail"
    assert TRANSPORT_MODES["3"][1] == "Air"
    assert TRANSPORT_MODES["4"][1] == "Ship"
