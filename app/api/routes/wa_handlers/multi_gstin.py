# app/api/routes/wa_handlers/multi_gstin.py
"""Multi-GSTIN management handler (Phase 8).

States handled:
    MULTI_GSTIN_MENU, MULTI_GSTIN_ADD, MULTI_GSTIN_LABEL, MULTI_GSTIN_SUMMARY
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

from app.domain.services.gstin_pan_validation import is_valid_gstin

logger = logging.getLogger("wa_handlers.multi_gstin")

# State constants
MULTI_GSTIN_MENU = "MULTI_GSTIN_MENU"
MULTI_GSTIN_ADD = "MULTI_GSTIN_ADD"
MULTI_GSTIN_LABEL = "MULTI_GSTIN_LABEL"
MULTI_GSTIN_SUMMARY = "MULTI_GSTIN_SUMMARY"

HANDLED_STATES = {
    MULTI_GSTIN_MENU,
    MULTI_GSTIN_ADD,
    MULTI_GSTIN_LABEL,
    MULTI_GSTIN_SUMMARY,
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
    """Handle multi-GSTIN management states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    if state == MULTI_GSTIN_MENU:
        if text == "1":
            session["state"] = MULTI_GSTIN_ADD
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "MULTI_GSTIN_ADD_PROMPT"))
            return Response(status_code=200)
        elif text == "2":
            await send(wa_id, "Enter the GSTIN number to switch to:")
            return Response(status_code=200)
        elif text == "3":
            session["state"] = MULTI_GSTIN_SUMMARY
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "MULTI_GSTIN_SUMMARY"))
            return Response(status_code=200)
        else:
            await send(wa_id, t(session, "MULTI_GSTIN_MENU"))
            return Response(status_code=200)

    if state == MULTI_GSTIN_ADD:
        new_gstin = text.strip().upper()
        if is_valid_gstin(new_gstin):
            session.setdefault("data", {})["pending_gstin"] = new_gstin
            session["state"] = MULTI_GSTIN_LABEL
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "MULTI_GSTIN_LABEL_PROMPT"))
        else:
            await send(wa_id, "Invalid GSTIN format. Please enter a valid 15-character GSTIN:")
        return Response(status_code=200)

    if state == MULTI_GSTIN_LABEL:
        label = text.strip()
        new_gstin = session.get("data", {}).get("pending_gstin", "")
        from app.domain.services.multi_gstin_service import add_gstin

        try:
            from app.core.db import get_db as _get_db

            async for _db in _get_db():
                result = await add_gstin(0, new_gstin, label, _db)
                if result["success"]:
                    await send(wa_id, t(session, "MULTI_GSTIN_ADDED", gstin=new_gstin, label=label))
                else:
                    await send(wa_id, f"❌ {result['error']}")
                break
        except Exception:
            logger.exception("Multi-GSTIN add error")
            await send(wa_id, "Error adding GSTIN. Please try again.")
        session["state"] = MULTI_GSTIN_MENU
        session.get("data", {}).pop("pending_gstin", None)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    if state == MULTI_GSTIN_SUMMARY:
        session["state"] = MULTI_GSTIN_MENU
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "MULTI_GSTIN_MENU"))
        return Response(status_code=200)

    return None
