# app/api/routes/wa_handlers/refund_notice.py
"""Refund tracking, notice management & export services handler (Phase 9).

States handled:
    REFUND_MENU, REFUND_TYPE, REFUND_DETAILS,
    NOTICE_MENU, NOTICE_UPLOAD,
    EXPORT_MENU
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.refund_notice")

# State constants
REFUND_MENU = "REFUND_MENU"
REFUND_TYPE = "REFUND_TYPE"
REFUND_DETAILS = "REFUND_DETAILS"
NOTICE_MENU = "NOTICE_MENU"
NOTICE_UPLOAD = "NOTICE_UPLOAD"
EXPORT_MENU = "EXPORT_MENU"

HANDLED_STATES = {
    REFUND_MENU,
    REFUND_TYPE,
    REFUND_DETAILS,
    NOTICE_MENU,
    NOTICE_UPLOAD,
    EXPORT_MENU,
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
    """Handle refund, notice and export states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    # ----- Refund Tracking -----
    if state == REFUND_MENU:
        if text == "1":
            session["state"] = REFUND_TYPE
            await session_cache.save_session(wa_id, session)
            await send(
                wa_id,
                "Select refund type:\n\n1) Excess Balance\n2) Export Refund\n3) Inverted Duty\n\nBACK = Go Back",
            )
            return Response(status_code=200)
        elif text == "2":
            gstin = session.get("data", {}).get("gstin", "")
            from app.domain.services.refund_service import list_refund_claims

            try:
                from app.core.db import get_db as _get_db

                async for _db in _get_db():
                    claims = await list_refund_claims(gstin, _db)
                    if claims:
                        lines = ["📋 Your Refund Claims:\n"]
                        for c in claims:
                            lines.append(
                                f"• {c['claim_type']} — ₹{c['amount']:,.2f} — {c['status']}"
                            )
                        lines.append("\nMENU = Main Menu\nBACK = Go Back")
                        await send(wa_id, "\n".join(lines))
                    else:
                        await send(wa_id, "No refund claims found.\n\nMENU = Main Menu\nBACK = Go Back")
                    break
            except Exception:
                await send(wa_id, "Error fetching refund claims.\n\nMENU = Main Menu\nBACK = Go Back")
            return Response(status_code=200)
        else:
            await send(wa_id, t(session, "REFUND_MENU"))
            return Response(status_code=200)

    if state == REFUND_TYPE:
        type_map = {"1": "excess_balance", "2": "export", "3": "inverted_duty"}
        if text in type_map:
            session.setdefault("data", {})["refund_type"] = type_map[text]
            session["state"] = REFUND_DETAILS
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "Enter the refund amount (in ₹):")
        else:
            await send(wa_id, "Invalid choice. Select 1, 2, or 3:")
        return Response(status_code=200)

    if state == REFUND_DETAILS:
        try:
            amount = float(text.replace(",", "").replace("₹", "").strip())
        except ValueError:
            await send(wa_id, "Please enter a valid amount (e.g. 50000):")
            return Response(status_code=200)

        from app.domain.services.gst_service import get_current_gst_period

        gstin = session.get("data", {}).get("gstin", "")
        claim_type = session.get("data", {}).get("refund_type", "excess_balance")
        period = get_current_gst_period()
        from app.domain.services.refund_service import create_refund_claim

        try:
            from app.core.db import get_db as _get_db

            async for _db in _get_db():
                result = await create_refund_claim(gstin, 0, claim_type, amount, period, _db)
                await send(
                    wa_id,
                    f"✅ Refund claim created!\n\nType: {claim_type}\nAmount: ₹{amount:,.2f}"
                    f"\nPeriod: {period}\nStatus: {result['status']}\n\nMENU = Main Menu\nBACK = Go Back",
                )
                break
        except Exception:
            logger.exception("Refund claim creation error")
            await send(wa_id, "Error creating refund claim.\n\nMENU = Main Menu\nBACK = Go Back")
        session["state"] = pop_state(session)
        session.get("data", {}).pop("refund_type", None)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    # ----- Notice Management -----
    if state == NOTICE_MENU:
        if text == "1":
            gstin = session.get("data", {}).get("gstin", "")
            from app.domain.services.notice_service import list_pending_notices

            try:
                from app.core.db import get_db as _get_db

                async for _db in _get_db():
                    notices = await list_pending_notices(gstin, _db)
                    if notices:
                        lines = ["📋 Pending Notices:\n"]
                        for n in notices:
                            due = n.get("due_date", "N/A")
                            lines.append(
                                f"• {n['notice_type']}: {n['description'][:50]}... (Due: {due})"
                            )
                        lines.append("\nMENU = Main Menu\nBACK = Go Back")
                        await send(wa_id, "\n".join(lines))
                    else:
                        await send(
                            wa_id, "✅ No pending notices!\n\nMENU = Main Menu\nBACK = Go Back"
                        )
                    break
            except Exception:
                await send(wa_id, "Error fetching notices.\n\nMENU = Main Menu\nBACK = Go Back")
            return Response(status_code=200)
        elif text == "2":
            session["state"] = NOTICE_UPLOAD
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "Upload the notice document (photo/PDF):")
            return Response(status_code=200)
        else:
            await send(wa_id, t(session, "NOTICE_MENU"))
            return Response(status_code=200)

    if state == NOTICE_UPLOAD:
        if text.lower() == "done":
            session["state"] = NOTICE_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "NOTICE_MENU"))
        else:
            await send(
                wa_id,
                "Upload a photo or PDF of the GST notice, or type 'done' to go back.",
            )
        return Response(status_code=200)

    # ----- Export Services -----
    if state == EXPORT_MENU:
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, "Export services feature coming soon!\n\nMENU = Main Menu\nBACK = Go Back")
        return Response(status_code=200)

    return None
