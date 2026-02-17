# app/domain/services/einvoice_flow.py
"""
e-Invoice (IRN) business logic for WhatsApp conversational flow.

Wraps the low-level ``EInvoiceClient`` with session-friendly helpers
for the step-by-step IRN generation, status check, and cancellation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("einvoice_flow")


async def prepare_irn_payload(invoice_dict: dict, gstin: str) -> dict:
    """Build the IRN generation payload from a parsed invoice dict.

    Parameters
    ----------
    invoice_dict : dict
        Parsed invoice data (from OCR / Vision).
    gstin : str
        Supplier GSTIN.

    Returns
    -------
    dict
        Payload suitable for ``EInvoiceClient.generate_irn()``.
    """
    return {
        "DocDtls": {
            "Typ": "INV",
            "No": invoice_dict.get("invoice_number", ""),
            "Dt": invoice_dict.get("invoice_date", ""),
        },
        "SellerDtls": {"Gstin": gstin},
        "BuyerDtls": {"Gstin": invoice_dict.get("receiver_gstin", "")},
        "ValDtls": {
            "TotInvVal": invoice_dict.get("total_amount", 0),
            "AssVal": invoice_dict.get("taxable_value", 0),
            "CgstVal": invoice_dict.get("cgst_amount", 0),
            "SgstVal": invoice_dict.get("sgst_amount", 0),
            "IgstVal": invoice_dict.get("igst_amount", 0),
        },
    }


async def generate_irn_for_invoice(gstin: str, invoice_dict: dict) -> dict[str, Any]:
    """Generate an IRN for a single invoice.

    Returns
    -------
    dict
        ``{"success": True, "irn": "...", "ack_no": "...", "ack_date": "..."}``
        or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.external.einvoice_client import EInvoiceClient, EInvoiceError

    if not EInvoiceClient.is_configured():
        return {"success": False, "error": "e-Invoice service not configured"}

    try:
        client = EInvoiceClient()
        auth_token = await client.authenticate(gstin)
        payload = await prepare_irn_payload(invoice_dict, gstin)
        resp = await client.generate_irn(gstin, auth_token, payload)

        data = resp.get("data", {}) or {}
        return {
            "success": True,
            "irn": data.get("Irn", "N/A"),
            "ack_no": data.get("AckNo", "N/A"),
            "ack_date": data.get("AckDt", "N/A"),
        }
    except EInvoiceError as e:
        logger.error("e-Invoice generation error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception:
        logger.exception("Unexpected error generating IRN")
        return {"success": False, "error": "Unexpected error generating IRN"}


async def get_irn_status(gstin: str, irn: str) -> dict[str, Any]:
    """Check the status of an existing IRN.

    Returns
    -------
    dict
        ``{"success": True, "status": "...", "details": {...}}``
        or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.external.einvoice_client import EInvoiceClient, EInvoiceError

    if not EInvoiceClient.is_configured():
        return {"success": False, "error": "e-Invoice service not configured"}

    try:
        client = EInvoiceClient()
        auth_token = await client.authenticate(gstin)
        resp = await client.get_irn_details(gstin, auth_token, irn)
        data = resp.get("data", {}) or {}
        return {
            "success": True,
            "status": data.get("Status", "Unknown"),
            "details": data,
        }
    except EInvoiceError as e:
        logger.error("e-Invoice status check error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception:
        logger.exception("Unexpected error checking IRN status")
        return {"success": False, "error": "Unexpected error checking IRN status"}


async def cancel_irn(gstin: str, irn: str, reason: str = "Data entry error") -> dict[str, Any]:
    """Cancel an existing IRN.

    Returns
    -------
    dict
        ``{"success": True, "message": "..."}``
        or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.external.einvoice_client import EInvoiceClient, EInvoiceError

    if not EInvoiceClient.is_configured():
        return {"success": False, "error": "e-Invoice service not configured"}

    try:
        client = EInvoiceClient()
        auth_token = await client.authenticate(gstin)
        resp = await client.cancel_irn(gstin, auth_token, irn, reason)
        return {"success": True, "message": f"IRN {irn} cancelled successfully"}
    except EInvoiceError as e:
        logger.error("e-Invoice cancellation error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception:
        logger.exception("Unexpected error cancelling IRN")
        return {"success": False, "error": "Unexpected error cancelling IRN"}
