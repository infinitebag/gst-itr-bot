# tests/test_einvoice_flow.py
"""Tests for e-Invoice flow service (Phase 6A)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.services.einvoice_flow import (
    prepare_irn_payload,
    generate_irn_for_invoice,
    get_irn_status,
    cancel_irn,
)

# The functions use deferred imports, so we patch at the source module
_EINVOICE_CLIENT_PATH = "app.infrastructure.external.einvoice_client.EInvoiceClient"


def test_prepare_irn_payload(event_loop):
    invoice = {
        "invoice_number": "INV-001",
        "invoice_date": "2025-01-15",
        "receiver_gstin": "29AAECC1206D1ZM",
        "total_amount": 50000,
        "taxable_value": 42373,
        "cgst_amount": 3813,
        "sgst_amount": 3813,
        "igst_amount": 0,
    }
    payload = event_loop.run_until_complete(
        prepare_irn_payload(invoice, "36AABCU9603R1ZM")
    )
    assert payload["DocDtls"]["No"] == "INV-001"
    assert payload["DocDtls"]["Dt"] == "2025-01-15"
    assert payload["SellerDtls"]["Gstin"] == "36AABCU9603R1ZM"
    assert payload["BuyerDtls"]["Gstin"] == "29AAECC1206D1ZM"
    assert payload["ValDtls"]["TotInvVal"] == 50000
    assert payload["ValDtls"]["CgstVal"] == 3813
    assert payload["ValDtls"]["SgstVal"] == 3813


def test_prepare_irn_payload_missing_fields(event_loop):
    """Missing fields should default to empty/zero."""
    payload = event_loop.run_until_complete(
        prepare_irn_payload({}, "36AABCU9603R1ZM")
    )
    assert payload["DocDtls"]["No"] == ""
    assert payload["ValDtls"]["TotInvVal"] == 0


def test_generate_irn_not_configured(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = False
        result = event_loop.run_until_complete(
            generate_irn_for_invoice("36AABCU9603R1ZM", {})
        )
        assert result["success"] is False
        assert "not configured" in result["error"]


def test_generate_irn_success(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.return_value = "test_token"
        mock_client.generate_irn.return_value = {
            "data": {"Irn": "IRN123456", "AckNo": "12345", "AckDt": "2025-01-15"}
        }
        invoice = {
            "invoice_number": "INV-001",
            "invoice_date": "2025-01-15",
            "total_amount": 50000,
            "taxable_value": 42373,
        }
        result = event_loop.run_until_complete(
            generate_irn_for_invoice("36AABCU9603R1ZM", invoice)
        )
        assert result["success"] is True
        assert result["irn"] == "IRN123456"
        assert result["ack_no"] == "12345"


def test_generate_irn_api_error(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.return_value = "test_token"
        from app.infrastructure.external.einvoice_client import EInvoiceError
        mock_client.generate_irn.side_effect = EInvoiceError("API error")
        result = event_loop.run_until_complete(
            generate_irn_for_invoice("36AABCU9603R1ZM", {"invoice_number": "X"})
        )
        assert result["success"] is False
        assert "API error" in result["error"]


def test_generate_irn_unexpected_error(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.side_effect = RuntimeError("network error")
        result = event_loop.run_until_complete(
            generate_irn_for_invoice("36AABCU9603R1ZM", {"invoice_number": "X"})
        )
        assert result["success"] is False
        assert "Unexpected" in result["error"]


def test_get_irn_status_not_configured(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = False
        result = event_loop.run_until_complete(
            get_irn_status("36AABCU9603R1ZM", "IRN123")
        )
        assert result["success"] is False


def test_get_irn_status_success(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.return_value = "test_token"
        mock_client.get_irn_details.return_value = {
            "data": {"Status": "Active"}
        }
        result = event_loop.run_until_complete(
            get_irn_status("36AABCU9603R1ZM", "IRN123")
        )
        assert result["success"] is True
        assert result["status"] == "Active"


def test_cancel_irn_success(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = True
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.authenticate.return_value = "test_token"
        mock_client.cancel_irn.return_value = {"status": "cancelled"}
        result = event_loop.run_until_complete(
            cancel_irn("36AABCU9603R1ZM", "IRN123")
        )
        assert result["success"] is True
        assert "IRN123" in result["message"]


def test_cancel_irn_not_configured(event_loop):
    with patch(_EINVOICE_CLIENT_PATH) as mock_cls:
        mock_cls.is_configured.return_value = False
        result = event_loop.run_until_complete(
            cancel_irn("36AABCU9603R1ZM", "IRN123")
        )
        assert result["success"] is False
