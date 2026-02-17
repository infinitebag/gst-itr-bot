# app/api/routes/wa_handlers/settings_handler.py
"""
Settings handler — Language, Profile, Segment view, Change Number entry.

States handled:
    SETTINGS_MENU        — main settings menu (5 options)
    SETTINGS_PROFILE     — show user profile summary
    SETTINGS_SEGMENT_VIEW — show current segment with option to request change
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

from app.domain.i18n import LANG_NAMES

logger = logging.getLogger("wa_handlers.settings_handler")

# State constants
SETTINGS_MENU = "SETTINGS_MENU"
SETTINGS_PROFILE = "SETTINGS_PROFILE"
SETTINGS_SEGMENT_VIEW = "SETTINGS_SEGMENT_VIEW"

LANG_MENU = "LANG_MENU"
MAIN_MENU = "MAIN_MENU"
CHANGE_NUMBER_START = "CHANGE_NUMBER_START"

HANDLED_STATES = {
    SETTINGS_MENU,
    SETTINGS_PROFILE,
    SETTINGS_SEGMENT_VIEW,
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
    """Handle settings states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    # ── SETTINGS_MENU ────────────────────────────────────────
    if state == SETTINGS_MENU:
        choice = text.strip()

        if choice == "1":
            # Language
            push_state(session, SETTINGS_MENU)
            session["state"] = LANG_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "LANG_MENU"))
            return Response(status_code=200)

        if choice == "2":
            # Profile
            push_state(session, SETTINGS_MENU)
            session["state"] = SETTINGS_PROFILE
            await session_cache.save_session(wa_id, session)
            await _show_profile(wa_id, session, send=send, t=t)
            return Response(status_code=200)

        if choice == "3":
            # View Segment
            push_state(session, SETTINGS_MENU)
            session["state"] = SETTINGS_SEGMENT_VIEW
            await session_cache.save_session(wa_id, session)
            await _show_segment(wa_id, session, send=send, t=t)
            return Response(status_code=200)

        if choice == "4":
            # Change Mobile Number — route to change_number handler
            push_state(session, SETTINGS_MENU)
            session["state"] = CHANGE_NUMBER_START
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CHANGE_NUMBER_START"))
            return Response(status_code=200)

        # Invalid — re-show settings
        await send(wa_id, t(session, "SETTINGS_MENU"))
        return Response(status_code=200)

    # ── SETTINGS_PROFILE ─────────────────────────────────────
    if state == SETTINGS_PROFILE:
        # Any text input returns to settings
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, state_to_screen_key(session["state"])))
        return Response(status_code=200)

    # ── SETTINGS_SEGMENT_VIEW ────────────────────────────────
    if state == SETTINGS_SEGMENT_VIEW:
        choice = text.strip()
        if choice == "1":
            # Record segment change request in session data for CA/admin review
            import time as _time
            data = session.setdefault("data", {})
            current_segment = data.get("client_segment", "small")
            data["segment_change_request"] = {
                "from_segment": current_segment,
                "requested_at": _time.time(),
                "status": "pending",
            }
            logger.info(
                "Segment change request from %s (current: %s)",
                wa_id, current_segment,
            )
            await send(wa_id, t(session, "SEGMENT_CHANGE_REQUESTED"))
        # Return to settings
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, state_to_screen_key(session["state"])))
        return Response(status_code=200)

    return None


# ══════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════

async def _show_profile(wa_id: str, session: dict, *, send, t):
    """Show user profile summary."""
    from app.domain.services.pii_masking import mask_gstin_display, mask_email

    data = session.get("data", {})
    lang = session.get("lang", "en")

    name = data.get("business_name") or "Not set"
    gstin = data.get("gstin")
    masked_gstin = mask_gstin_display(gstin) if gstin else "Not set"
    lang_name = LANG_NAMES.get(lang, "English")

    await send(wa_id, t(session, "SETTINGS_PROFILE_DISPLAY",
                        name=name,
                        gstin=masked_gstin,
                        language=lang_name))


async def _show_segment(wa_id: str, session: dict, *, send, t):
    """Show current segment info."""
    data = session.get("data", {})
    segment = data.get("client_segment", "small")

    # Map internal segment to display label
    _LABELS = {
        "en": {"small": "Small", "medium": "Medium", "enterprise": "Large"},
        "hi": {"small": "छोटा", "medium": "मध्यम", "enterprise": "बड़ा"},
        "gu": {"small": "નાનું", "medium": "મધ્યમ", "enterprise": "મોટું"},
        "ta": {"small": "சிறியது", "medium": "நடுத்தரம்", "enterprise": "பெரியது"},
        "te": {"small": "చిన్నది", "medium": "మధ్యస్థం", "enterprise": "పెద్దది"},
        "kn": {"small": "ಚಿಕ್ಕದು", "medium": "ಮಧ್ಯಮ", "enterprise": "ದೊಡ್ಡದು"},
    }
    lang = session.get("lang", "en")
    lang_labels = _LABELS.get(lang, _LABELS["en"])
    segment_label = lang_labels.get(segment, segment)

    await send(wa_id, t(session, "SETTINGS_SEGMENT_DISPLAY", segment=segment_label))
