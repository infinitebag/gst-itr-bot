# app/api/routes/wa_handlers/session_expiry.py
"""
Session expiry handler — resume prompt and sensitive timeout.

States handled:
    SESSION_RESUME_PROMPT    — shown after 30-min idle
    SENSITIVE_CONFIRM_EXPIRED — shown when a confirm screen timed out (10-min)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.session_expiry")

# State constants
SESSION_RESUME_PROMPT = "SESSION_RESUME_PROMPT"
SENSITIVE_CONFIRM_EXPIRED = "SENSITIVE_CONFIRM_EXPIRED"

MAIN_MENU = "MAIN_MENU"

HANDLED_STATES = {
    SESSION_RESUME_PROMPT,
    SENSITIVE_CONFIRM_EXPIRED,
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
    """Handle session expiry states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    # ── SESSION_RESUME_PROMPT ────────────────────────────────
    if state == SESSION_RESUME_PROMPT:
        choice = text.strip()
        data = session.setdefault("data", {})
        pre_state = data.get("pre_expiry_state", MAIN_MENU)

        if choice == "1":
            # Continue — restore previous state
            session["state"] = pre_state
            data.pop("pre_expiry_state", None)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, state_to_screen_key(session["state"])))
            return Response(status_code=200)

        if choice == "2":
            # Start Over — clear flow data, show current module menu
            # Determine which module they were in
            module_menu = _module_menu_for_state(pre_state)
            _clear_flow_data(data)
            session["state"] = module_menu
            data.pop("pre_expiry_state", None)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, state_to_screen_key(module_menu)))
            return Response(status_code=200)

        if choice == "3":
            # Main Menu
            _clear_flow_data(data)
            session["state"] = MAIN_MENU
            data.pop("pre_expiry_state", None)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "WELCOME_MENU"))
            return Response(status_code=200)

        # Invalid — re-show
        await send(wa_id, t(session, "SESSION_RESUME_PROMPT"))
        return Response(status_code=200)

    # ── SENSITIVE_CONFIRM_EXPIRED ────────────────────────────
    if state == SENSITIVE_CONFIRM_EXPIRED:
        # Any input → go back to the state that needs re-confirmation
        pre_state = session.get("data", {}).get("pre_expiry_state", MAIN_MENU)
        session["state"] = pre_state
        session.get("data", {}).pop("pre_expiry_state", None)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, state_to_screen_key(pre_state)))
        return Response(status_code=200)

    return None


def _module_menu_for_state(state: str) -> str:
    """Determine which module menu a state belongs to."""
    gst_prefixes = ("GST_", "SMALL_WIZARD", "MEDIUM_", "EINVOICE_", "EWAYBILL_",
                    "MULTI_GSTIN", "NIL_FILING", "WAIT_GSTIN")
    itr_prefixes = ("ITR", "ITR1_", "ITR2_", "ITR4_")
    ca_prefixes = ("CONNECT_CA_",)

    for prefix in gst_prefixes:
        if state.startswith(prefix):
            return "GST_MENU"
    for prefix in itr_prefixes:
        if state.startswith(prefix):
            return "ITR_MENU"
    for prefix in ca_prefixes:
        if state.startswith(prefix):
            return "CONNECT_CA_MENU"

    return "MAIN_MENU"


def _clear_flow_data(data: dict) -> None:
    """Clear transient flow data while keeping persistent stuff."""
    # Keep: gstin, business_name, client_segment, gst_onboarded, lang-related
    # Clear: wizard data, filing data, payment data
    for key in list(data.keys()):
        if key in ("gstin", "business_name", "client_segment", "gst_onboarded",
                    "filing_mode", "turnover_band", "multi_gstin", "additional_gstins"):
            continue
        if key.startswith(("wizard_", "payment_", "gst_filing_", "itr_")):
            del data[key]
