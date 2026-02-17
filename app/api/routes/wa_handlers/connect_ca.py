# app/api/routes/wa_handlers/connect_ca.py
"""
Connect with CA (Chartered Accountant) handler.

States handled:
    CONNECT_CA_MENU     — main menu: Ask Question, Request Call, Share Docs
    CONNECT_CA_ASK_TEXT — user types a question for the CA
    CONNECT_CA_CALL_TIME — user picks a callback time slot
    CONNECT_CA_SHARE_DOCS — user is prompted to upload a document
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.connect_ca")

# State constants
CONNECT_CA_MENU = "CONNECT_CA_MENU"
CONNECT_CA_ASK_TEXT = "CONNECT_CA_ASK_TEXT"
CONNECT_CA_CALL_TIME = "CONNECT_CA_CALL_TIME"
CONNECT_CA_SHARE_DOCS = "CONNECT_CA_SHARE_DOCS"

MAIN_MENU = "MAIN_MENU"

HANDLED_STATES = {
    CONNECT_CA_MENU,
    CONNECT_CA_ASK_TEXT,
    CONNECT_CA_CALL_TIME,
    CONNECT_CA_SHARE_DOCS,
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
    """Handle Connect with CA states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    # ── CONNECT_CA_MENU ──────────────────────────────────────
    if state == CONNECT_CA_MENU:
        choice = text.strip()

        if choice == "1":
            # Ask a Question
            push_state(session, CONNECT_CA_MENU)
            session["state"] = CONNECT_CA_ASK_TEXT
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CA_ASK_QUESTION_PROMPT"))
            return Response(status_code=200)

        if choice == "2":
            # Request a Call
            push_state(session, CONNECT_CA_MENU)
            session["state"] = CONNECT_CA_CALL_TIME
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CA_CALL_TIME_PROMPT"))
            return Response(status_code=200)

        if choice == "3":
            # Share Documents
            push_state(session, CONNECT_CA_MENU)
            session["state"] = CONNECT_CA_SHARE_DOCS
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CA_SHARE_DOCS_PROMPT"))
            return Response(status_code=200)

        # Invalid — re-show menu
        await send(wa_id, t(session, "CONNECT_CA_MENU"))
        return Response(status_code=200)

    # ── CONNECT_CA_ASK_TEXT ───────────────────────────────────
    if state == CONNECT_CA_ASK_TEXT:
        question = text.strip()
        if len(question) < 3:
            await send(wa_id, t(session, "CA_ASK_QUESTION_TOO_SHORT"))
            return Response(status_code=200)

        # Store question (in production, save to DB and notify CA)
        logger.info("CA question from %s: %s", wa_id, question[:100])
        session.setdefault("data", {}).setdefault("ca_questions", []).append(question)

        session["state"] = CONNECT_CA_MENU
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "CA_QUESTION_RECEIVED"))
        return Response(status_code=200)

    # ── CONNECT_CA_CALL_TIME ──────────────────────────────────
    if state == CONNECT_CA_CALL_TIME:
        choice = text.strip()
        time_map = {"1": "morning", "2": "afternoon", "3": "evening"}

        if choice not in time_map:
            await send(wa_id, t(session, "CA_CALL_TIME_PROMPT"))
            return Response(status_code=200)

        time_slot = time_map[choice]
        logger.info("CA callback request from %s: %s", wa_id, time_slot)
        session.setdefault("data", {})["ca_callback_time"] = time_slot

        session["state"] = CONNECT_CA_MENU
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "CA_CALL_REQUESTED", time_slot=time_slot))
        return Response(status_code=200)

    # ── CONNECT_CA_SHARE_DOCS ─────────────────────────────────
    if state == CONNECT_CA_SHARE_DOCS:
        # This state just shows the prompt.
        # Actual document upload (image/document) is handled in whatsapp.py
        # If user sends text instead of a file, remind them.
        await send(wa_id, t(session, "CA_SHARE_DOCS_PROMPT"))
        return Response(status_code=200)

    return None
