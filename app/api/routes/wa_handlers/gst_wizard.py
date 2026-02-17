# app/api/routes/wa_handlers/gst_wizard.py
"""Small-segment guided wizard handler (Phase 7A).

States handled:
    SMALL_WIZARD_SALES, SMALL_WIZARD_PURCHASES, SMALL_WIZARD_CONFIRM
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.gst_wizard")

# State constants
SMALL_WIZARD_SALES = "SMALL_WIZARD_SALES"
SMALL_WIZARD_PURCHASES = "SMALL_WIZARD_PURCHASES"
SMALL_WIZARD_CONFIRM = "SMALL_WIZARD_CONFIRM"
GST_MENU = "GST_MENU"

HANDLED_STATES = {
    SMALL_WIZARD_SALES,
    SMALL_WIZARD_PURCHASES,
    SMALL_WIZARD_CONFIRM,
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
    """Handle small-segment wizard states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    if state == SMALL_WIZARD_SALES:
        if text.lower() == "done":
            sales = session.get("data", {}).get("wizard_sales_invoices", [])
            from app.domain.services.gst_explainer import compute_sales_tax, detect_nil_return

            if detect_nil_return(sales):
                await send(wa_id, t(session, "WIZARD_NIL_DETECT"))
                session["state"] = GST_MENU
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)
            sales_tax = compute_sales_tax(sales)
            await send(
                wa_id,
                t(session, "WIZARD_SALES_DONE", sales_tax=f"₹{sales_tax:,.2f}", count=len(sales)),
            )
            session["state"] = SMALL_WIZARD_PURCHASES
            session.setdefault("data", {})["wizard_purchase_invoices"] = []
            session["data"]["wizard_sales_tax"] = sales_tax
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "WIZARD_PURCHASE_PROMPT"))
            return Response(status_code=200)
        await send(wa_id, "📸 Upload sales bills (photos/PDFs). Send 'done' when finished.")
        return Response(status_code=200)

    if state == SMALL_WIZARD_PURCHASES:
        if text.lower() == "done":
            purchases = session.get("data", {}).get("wizard_purchase_invoices", [])
            from app.domain.services.gst_explainer import (
                compute_purchase_credit,
                format_simple_summary,
            )

            sales = session.get("data", {}).get("wizard_sales_invoices", [])
            lang = get_lang(session) if get_lang else "en"
            segment = session.get("data", {}).get("client_segment", "small")
            summary = format_simple_summary(sales, purchases, lang, segment)
            session["state"] = SMALL_WIZARD_CONFIRM
            await session_cache.save_session(wa_id, session)
            await send(wa_id, summary)
            await send_buttons(
                wa_id,
                t(session, "WIZARD_CONFIRM"),
                [
                    {"id": "wiz_send_ca", "title": "✅ Send to CA"},
                    {"id": "wiz_edit", "title": "📝 Make Changes"},
                    {"id": "wiz_cancel", "title": "❌ Cancel"},
                ],
            )
            return Response(status_code=200)
        await send(wa_id, "📸 Upload purchase bills for credit. Send 'done' when finished.")
        return Response(status_code=200)

    if state == SMALL_WIZARD_CONFIRM:
        if text in ("wiz_send_ca", "1"):
            await send(wa_id, t(session, "WIZARD_SENT_TO_CA"))
            session["state"] = GST_MENU
            for k in ("wizard_sales_invoices", "wizard_purchase_invoices", "wizard_sales_tax"):
                session.get("data", {}).pop(k, None)
            await session_cache.save_session(wa_id, session)
        elif text in ("wiz_edit", "2"):
            session["state"] = SMALL_WIZARD_SALES
            session.setdefault("data", {})["wizard_sales_invoices"] = []
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "WIZARD_SALES_PROMPT"))
        else:
            session["state"] = GST_MENU
            for k in ("wizard_sales_invoices", "wizard_purchase_invoices", "wizard_sales_tax"):
                session.get("data", {}).pop(k, None)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "Cancelled. Returning to GST menu.\n\nMENU = Main Menu")
        return Response(status_code=200)

    return None
