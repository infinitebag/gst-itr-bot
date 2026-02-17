# app/domain/services/ewaybill_flow.py
"""
e-WayBill business logic for WhatsApp conversational flow.

Wraps the low-level ``EWayBillClient`` with session-friendly helpers
for step-by-step EWB generation, tracking, vehicle updates.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ewaybill_flow")

# Transport mode mapping
TRANSPORT_MODES = {
    "1": ("1", "Road"),
    "2": ("2", "Rail"),
    "3": ("3", "Air"),
    "4": ("4", "Ship"),
}


async def prepare_ewb_payload(
    invoice_dict: dict,
    gstin: str,
    transport: dict,
) -> dict:
    """Build the e-WayBill generation payload.

    Parameters
    ----------
    invoice_dict : dict
        Parsed invoice data.
    gstin : str
        Supplier GSTIN.
    transport : dict
        Transport details: ``vehicle_no``, ``trans_mode``, ``distance``.
    """
    return {
        "supplyType": "O",  # Outward
        "docType": "INV",
        "docNo": invoice_dict.get("invoice_number", ""),
        "docDate": invoice_dict.get("invoice_date", ""),
        "fromGstin": gstin,
        "toGstin": invoice_dict.get("receiver_gstin", ""),
        "totInvValue": invoice_dict.get("total_amount", 0),
        "transMode": transport.get("trans_mode", "1"),
        "transactionType": 1,
        "vehicleNo": transport.get("vehicle_no", ""),
        "transDistance": transport.get("distance", "0"),
    }


async def generate_ewb(gstin: str, invoice_dict: dict, transport: dict) -> dict[str, Any]:
    """Generate an e-WayBill for a single invoice.

    Returns
    -------
    dict
        ``{"success": True, "ewb_no": "...", "valid_until": "..."}``
        or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.external.ewaybill_client import EWayBillClient, EWayBillError

    if not EWayBillClient.is_configured():
        return {"success": False, "error": "e-WayBill service not configured"}

    try:
        client = EWayBillClient()
        auth_token = await client.authenticate(gstin)
        payload = await prepare_ewb_payload(invoice_dict, gstin, transport)
        resp = await client.generate_ewaybill(gstin, auth_token, payload)

        data = resp.get("data", {}) or {}
        return {
            "success": True,
            "ewb_no": data.get("ewayBillNo", "N/A"),
            "valid_until": data.get("validUpto", "N/A"),
        }
    except EWayBillError as e:
        logger.error("e-WayBill generation error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception:
        logger.exception("Unexpected error generating e-WayBill")
        return {"success": False, "error": "Unexpected error generating e-WayBill"}


async def track_ewb(gstin: str, ewb_no: str) -> dict[str, Any]:
    """Track an existing e-WayBill.

    Returns
    -------
    dict
        ``{"success": True, "ewb_no": "...", "status": "...", ...}``
        or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.external.ewaybill_client import EWayBillClient, EWayBillError

    if not EWayBillClient.is_configured():
        return {"success": False, "error": "e-WayBill service not configured"}

    try:
        client = EWayBillClient()
        auth_token = await client.authenticate(gstin)
        resp = await client.get_ewaybill(gstin, auth_token, ewb_no)

        data = resp.get("data", {}) or {}
        return {
            "success": True,
            "ewb_no": ewb_no,
            "status": data.get("status", "Unknown"),
            "generated_date": data.get("ewayBillDate", "N/A"),
            "valid_until": data.get("validUpto", "N/A"),
        }
    except EWayBillError as e:
        logger.error("e-WayBill tracking error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception:
        logger.exception("Unexpected error tracking e-WayBill")
        return {"success": False, "error": "Unexpected error tracking e-WayBill"}


async def update_vehicle(
    gstin: str,
    ewb_no: str,
    vehicle_no: str,
    reason: str = "First Time",
) -> dict[str, Any]:
    """Update the vehicle number on an e-WayBill.

    Returns
    -------
    dict
        ``{"success": True, "message": "..."}``
        or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.external.ewaybill_client import EWayBillClient, EWayBillError

    if not EWayBillClient.is_configured():
        return {"success": False, "error": "e-WayBill service not configured"}

    try:
        client = EWayBillClient()
        auth_token = await client.authenticate(gstin)
        vehicle_data = {
            "ewbNo": ewb_no,
            "vehicleNo": vehicle_no,
            "reasonCode": "1",
            "reasonRem": reason,
            "transMode": "1",
        }
        await client.update_vehicle(gstin, auth_token, ewb_no, vehicle_data)
        return {"success": True, "message": f"Vehicle updated to {vehicle_no} for EWB {ewb_no}"}
    except EWayBillError as e:
        logger.error("e-WayBill vehicle update error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception:
        logger.exception("Unexpected error updating vehicle")
        return {"success": False, "error": "Unexpected error updating vehicle"}
