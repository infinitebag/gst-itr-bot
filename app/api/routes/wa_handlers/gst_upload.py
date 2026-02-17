# app/api/routes/wa_handlers/gst_upload.py
"""GST Upload sub-flow handler.

States handled:
    GST_UPLOAD_MENU  — choose upload type (sales / purchase / GSTR-2B)
    GSTR2B_UPLOAD    — prompt user to send their GSTR-2B portal file
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.gst_upload")

# State constants (must match whatsapp.py / other handlers)
GST_UPLOAD_MENU = "GST_UPLOAD_MENU"
GSTR2B_UPLOAD = "GSTR2B_UPLOAD"
SMART_UPLOAD = "SMART_UPLOAD"
GST_MENU = "GST_MENU"

HANDLED_STATES = {
    GST_UPLOAD_MENU,
    GSTR2B_UPLOAD,
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
    """Handle GST upload sub-flow states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    # ── GST_UPLOAD_MENU ──────────────────────────────────────────
    if state == GST_UPLOAD_MENU:
        return await _handle_upload_menu(
            text, wa_id, session,
            session_cache=session_cache,
            send=send,
            send_buttons=send_buttons,
            t=t,
            push_state=push_state,
        )

    # ── GSTR2B_UPLOAD ────────────────────────────────────────────
    if state == GSTR2B_UPLOAD:
        return await _handle_gstr2b_upload(
            text, wa_id, session,
            session_cache=session_cache,
            send=send,
            t=t,
            pop_state=pop_state,
        )

    return None


# ══════════════════════════════════════════════════════════════════
# State handlers
# ══════════════════════════════════════════════════════════════════

async def _handle_upload_menu(
    text: str, wa_id: str, session: dict, *,
    session_cache, send, send_buttons, t, push_state,
) -> Response:
    """GST_UPLOAD_MENU — present three upload options or route selection."""
    choice = text.strip().lower()

    # Option 1: Upload Sales Bills → SMART_UPLOAD
    if choice in ("upload_sales", "1"):
        logger.info("wa_id=%s selected Upload Sales Bills", wa_id)
        push_state(session, GST_UPLOAD_MENU)
        session["state"] = SMART_UPLOAD
        session.setdefault("data", {})["upload_type"] = "sales"
        await session_cache.save_session(wa_id, session)
        await send(
            wa_id,
            t(session, "SMART_UPLOAD_PROMPT"),
        )
        return Response(status_code=200)

    # Option 2: Upload Purchase Bills → SMART_UPLOAD with purchase flag
    if choice in ("upload_purchase", "2"):
        logger.info("wa_id=%s selected Upload Purchase Bills", wa_id)
        push_state(session, GST_UPLOAD_MENU)
        session["state"] = SMART_UPLOAD
        session.setdefault("data", {})["upload_type"] = "purchase"
        await session_cache.save_session(wa_id, session)
        await send(
            wa_id,
            t(session, "SMART_UPLOAD_PROMPT"),
        )
        return Response(status_code=200)

    # Option 3: Upload Portal Purchase File (GSTR-2B) → GSTR2B_UPLOAD
    if choice in ("upload_gstr2b", "3"):
        logger.info("wa_id=%s selected Upload GSTR-2B file", wa_id)
        push_state(session, GST_UPLOAD_MENU)
        session["state"] = GSTR2B_UPLOAD
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "GSTR2B_UPLOAD_PROMPT"))
        return Response(status_code=200)

    # BACK → return to GST_MENU
    if choice in ("back", "0"):
        logger.info("wa_id=%s going back to GST_MENU from upload menu", wa_id)
        session["state"] = GST_MENU
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    # Unrecognised input → re-show menu
    logger.debug("wa_id=%s unrecognised upload menu input: %s", wa_id, text)
    await send_buttons(
        wa_id,
        t(session, "GST_UPLOAD_MENU"),
        [
            {"id": "upload_sales", "title": "Upload Sales Bills"},
            {"id": "upload_purchase", "title": "Upload Purchase Bills"},
            {"id": "upload_gstr2b", "title": "Upload GSTR-2B File"},
        ],
    )
    return Response(status_code=200)


async def _handle_gstr2b_upload(
    text: str, wa_id: str, session: dict, *,
    session_cache, send, t, pop_state,
) -> Response:
    """GSTR2B_UPLOAD — prompt user to send their 2B JSON/Excel file.

    Actual file handling (document/media message) is done in whatsapp.py;
    this handler only manages the text-based prompt and back navigation.
    """
    choice = text.strip().lower()

    # BACK → return to upload menu
    if choice in ("back", "0"):
        logger.info("wa_id=%s going back from GSTR2B upload", wa_id)
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    # Any other text — remind user to upload the file
    logger.debug("wa_id=%s awaiting GSTR-2B file, got text: %s", wa_id, text)
    await send(
        wa_id,
        t(session, "GSTR2B_UPLOAD_PROMPT"),
    )
    return Response(status_code=200)
