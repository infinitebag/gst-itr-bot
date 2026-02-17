# app/api/routes/wa_handlers/einvoice.py
"""e-Invoice conversational flow handler (Phase 6A).

States handled:
    EINVOICE_MENU, EINVOICE_UPLOAD, EINVOICE_CONFIRM,
    EINVOICE_STATUS_ASK, EINVOICE_CANCEL
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.einvoice")

# State constants (must match whatsapp.py)
EINVOICE_MENU = "EINVOICE_MENU"
EINVOICE_UPLOAD = "EINVOICE_UPLOAD"
EINVOICE_CONFIRM = "EINVOICE_CONFIRM"
EINVOICE_STATUS_ASK = "EINVOICE_STATUS_ASK"
EINVOICE_CANCEL = "EINVOICE_CANCEL"
GST_MENU = "GST_MENU"

HANDLED_STATES = {
    EINVOICE_MENU,
    EINVOICE_UPLOAD,
    EINVOICE_CONFIRM,
    EINVOICE_STATUS_ASK,
    EINVOICE_CANCEL,
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
    """Handle e-Invoice states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    if state == EINVOICE_MENU:
        if text in ("einv_generate", "1"):
            session["state"] = EINVOICE_UPLOAD
            session.setdefault("data", {})["einvoice_invoices"] = []
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "EINVOICE_UPLOAD_PROMPT"))
            return Response(status_code=200)
        elif text in ("einv_status", "2"):
            session["state"] = EINVOICE_STATUS_ASK
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "EINVOICE_STATUS_PROMPT"))
            return Response(status_code=200)
        elif text in ("einv_cancel", "3"):
            session["state"] = EINVOICE_CANCEL
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "EINVOICE_CANCEL_PROMPT"))
            return Response(status_code=200)
        else:
            await send(wa_id, t(session, "EINVOICE_MENU"))
            return Response(status_code=200)

    if state == EINVOICE_UPLOAD:
        if text.lower() == "done":
            einv_invoices = session.get("data", {}).get("einvoice_invoices", [])
            if not einv_invoices:
                await send(
                    wa_id,
                    "No invoices uploaded yet. Please upload an invoice image/PDF or type 'done' to go back.",
                )
                return Response(status_code=200)
            # Show review
            lines = ["🧾 *Invoice Review*\n"]
            for i, inv in enumerate(einv_invoices, 1):
                lines.append(
                    f"{i}) Inv #{inv.get('invoice_number', '?')} — ₹{inv.get('total_amount', 0):,.2f}"
                )
            lines.append(f"\nTotal: {len(einv_invoices)} invoice(s)")
            lines.append("\nGenerate IRN for all? Reply 1=Yes, 2=Cancel")
            session["state"] = EINVOICE_CONFIRM
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "\n".join(lines))
            return Response(status_code=200)
        # Image/document upload handled by the invoice parsing pipeline
        await send(wa_id, "Upload your invoice (photo/PDF), or type 'done' when finished.")
        return Response(status_code=200)

    if state == EINVOICE_CONFIRM:
        if text == "1":
            gstin = session.get("data", {}).get("gstin", "")
            einv_invoices = session.get("data", {}).get("einvoice_invoices", [])
            await send(wa_id, t(session, "EINVOICE_GENERATING"))
            from app.domain.services.einvoice_flow import generate_irn_for_invoice

            results = []
            for inv in einv_invoices:
                result = await generate_irn_for_invoice(gstin, inv)
                if result["success"]:
                    results.append(
                        f"✅ Inv #{inv.get('invoice_number', '?')}: IRN={result['irn']}"
                    )
                else:
                    results.append(
                        f"❌ Inv #{inv.get('invoice_number', '?')}: {result['error']}"
                    )
            msg = "\n".join(results)
            await send(wa_id, t(session, "EINVOICE_IRN_SUCCESS", result_message=msg))
            session["state"] = GST_MENU
            session.get("data", {}).pop("einvoice_invoices", None)
            await session_cache.save_session(wa_id, session)
        else:
            session["state"] = GST_MENU
            session.get("data", {}).pop("einvoice_invoices", None)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "Cancelled. Returning to GST menu.")
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.whatsapp_menu_builder import build_gst_menu

                async for _db in _get_db():
                    menu_result = await build_gst_menu(wa_id, session, _db)
                    break
            except Exception:
                menu_result = t(session, "GST_SERVICES")
            await send_menu_result(wa_id, menu_result)
        return Response(status_code=200)

    if state == EINVOICE_STATUS_ASK:
        irn = text.strip()
        gstin = session.get("data", {}).get("gstin", "")
        from app.domain.services.einvoice_flow import get_irn_status

        result = await get_irn_status(gstin, irn)
        if result["success"]:
            await send(wa_id, f"📋 IRN Status: {result['status']}\n\nMENU = Main Menu\nBACK = Go Back")
        else:
            await send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    if state == EINVOICE_CANCEL:
        irn = text.strip()
        gstin = session.get("data", {}).get("gstin", "")
        from app.domain.services.einvoice_flow import cancel_irn

        result = await cancel_irn(gstin, irn)
        if result["success"]:
            await send(wa_id, t(session, "EINVOICE_CANCEL_SUCCESS", irn=irn))
        else:
            await send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    return None
