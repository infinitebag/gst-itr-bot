# app/api/routes/wa_handlers/ewaybill.py
"""e-WayBill conversational flow handler (Phase 6B).

States handled:
    EWAYBILL_MENU, EWAYBILL_UPLOAD, EWAYBILL_TRANSPORT,
    EWAYBILL_TRACK_ASK, EWAYBILL_VEHICLE_ASK
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.ewaybill")

# State constants (must match whatsapp.py)
EWAYBILL_MENU = "EWAYBILL_MENU"
EWAYBILL_UPLOAD = "EWAYBILL_UPLOAD"
EWAYBILL_TRANSPORT = "EWAYBILL_TRANSPORT"
EWAYBILL_TRACK_ASK = "EWAYBILL_TRACK_ASK"
EWAYBILL_VEHICLE_ASK = "EWAYBILL_VEHICLE_ASK"
GST_MENU = "GST_MENU"

HANDLED_STATES = {
    EWAYBILL_MENU,
    EWAYBILL_UPLOAD,
    EWAYBILL_TRANSPORT,
    EWAYBILL_TRACK_ASK,
    EWAYBILL_VEHICLE_ASK,
}


async def handle(
    state: str,
    text: str,
    wa_id: str,
    session: dict,
    *,
    session_cache: Any,
    send: Callable[..., Awaitable],
    send_buttons: Callable[..., Awaitable],
    send_menu_result: Callable[..., Awaitable],
    t: Callable,
    push_state: Callable,
    pop_state: Callable,
    state_to_screen_key: Callable,
    get_lang: Callable | None = None,
    **_extra: Any,
) -> Response | None:
    """Handle e-WayBill states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    if state == EWAYBILL_MENU:
        if text in ("ewb_generate", "1"):
            session["state"] = EWAYBILL_UPLOAD
            session.setdefault("data", {})["ewaybill_invoices"] = []
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "EWAYBILL_UPLOAD_PROMPT"))
            return Response(status_code=200)
        elif text in ("ewb_track", "2"):
            session["state"] = EWAYBILL_TRACK_ASK
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "EWAYBILL_TRACK_ASK"))
            return Response(status_code=200)
        elif text in ("ewb_vehicle", "3"):
            session["state"] = EWAYBILL_VEHICLE_ASK
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "EWAYBILL_VEHICLE_ASK"))
            return Response(status_code=200)
        else:
            await send(wa_id, t(session, "EWAYBILL_MENU"))
            return Response(status_code=200)

    if state == EWAYBILL_UPLOAD:
        if text.lower() == "done":
            ewb_invoices = session.get("data", {}).get("ewaybill_invoices", [])
            if not ewb_invoices:
                await send(
                    wa_id,
                    "No invoices uploaded yet. Please upload an invoice or type 'done' to go back.",
                )
                return Response(status_code=200)
            session["state"] = EWAYBILL_TRANSPORT
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "EWAYBILL_TRANSPORT_ASK"))
            return Response(status_code=200)
        await send(wa_id, "Upload your invoice (photo/PDF), or type 'done' when finished.")
        return Response(status_code=200)

    if state == EWAYBILL_TRANSPORT:
        parts = [p.strip() for p in text.split(",")]
        transport = {
            "vehicle_no": parts[0] if len(parts) > 0 else "",
            "mode": parts[1] if len(parts) > 1 else "Road",
            "distance": parts[2] if len(parts) > 2 else "0",
        }
        session.setdefault("data", {})["ewb_transport"] = transport
        gstin = session.get("data", {}).get("gstin", "")
        ewb_invoices = session.get("data", {}).get("ewaybill_invoices", [])
        await send(wa_id, t(session, "EWAYBILL_GENERATING"))
        from app.domain.services.ewaybill_flow import generate_ewb

        results = []
        for inv in ewb_invoices:
            result = await generate_ewb(gstin, inv, transport)
            if result["success"]:
                results.append(
                    f"✅ Inv #{inv.get('invoice_number', '?')}: EWB={result['ewb_no']}"
                )
            else:
                results.append(
                    f"❌ Inv #{inv.get('invoice_number', '?')}: {result['error']}"
                )
        msg = "\n".join(results)
        await send(wa_id, t(session, "EWAYBILL_SUCCESS", result_message=msg))
        session["state"] = GST_MENU
        session.get("data", {}).pop("ewaybill_invoices", None)
        session.get("data", {}).pop("ewb_transport", None)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    if state == EWAYBILL_TRACK_ASK:
        ewb_no = text.strip()
        gstin = session.get("data", {}).get("gstin", "")
        from app.domain.services.ewaybill_flow import track_ewb

        result = await track_ewb(gstin, ewb_no)
        if result["success"]:
            await send(
                wa_id,
                t(
                    session,
                    "EWAYBILL_TRACK_RESULT",
                    ewb_no=ewb_no,
                    status=result["status"],
                    valid_upto=result.get("valid_upto", "N/A"),
                ),
            )
        else:
            await send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    if state == EWAYBILL_VEHICLE_ASK:
        parts = [p.strip() for p in text.split(",")]
        ewb_no = parts[0] if len(parts) > 0 else ""
        vehicle_no = parts[1] if len(parts) > 1 else ""
        reason = parts[2] if len(parts) > 2 else "Vehicle breakdown"
        gstin = session.get("data", {}).get("gstin", "")
        from app.domain.services.ewaybill_flow import update_vehicle

        result = await update_vehicle(gstin, ewb_no, vehicle_no, reason)
        if result["success"]:
            await send(
                wa_id,
                f"✅ Vehicle updated for EWB {ewb_no}\nNew Vehicle: {vehicle_no}\n\nMENU = Main Menu\nBACK = Go Back",
            )
        else:
            await send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    return None
