# app/api/routes/wa_handlers/change_number.py
"""
Mobile number change handler — stubbed OTP + CA verification.

Paths:
  Email OTP:  Confirm email → Send OTP (stubbed) → Enter OTP → Success/Lock
  CA Verify:  Upload verification document → Pending CA approval

States handled:
    CHANGE_NUMBER_START          — choose verification method
    CHANGE_NUMBER_CONFIRM_EMAIL  — confirm/enter email for OTP
    CHANGE_NUMBER_ENTER_OTP      — enter OTP code
    CHANGE_NUMBER_SUCCESS        — success message
    CHANGE_NUMBER_LOCKED         — locked out
    CHANGE_NUMBER_CA_VERIFY      — upload document for CA verification
    CHANGE_NUMBER_CA_PENDING     — pending CA approval
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.change_number")

# State constants
CHANGE_NUMBER_START = "CHANGE_NUMBER_START"
CHANGE_NUMBER_CONFIRM_EMAIL = "CHANGE_NUMBER_CONFIRM_EMAIL"
CHANGE_NUMBER_ENTER_OTP = "CHANGE_NUMBER_ENTER_OTP"
CHANGE_NUMBER_SUCCESS = "CHANGE_NUMBER_SUCCESS"
CHANGE_NUMBER_LOCKED = "CHANGE_NUMBER_LOCKED"
CHANGE_NUMBER_CA_VERIFY = "CHANGE_NUMBER_CA_VERIFY"
CHANGE_NUMBER_CA_PENDING = "CHANGE_NUMBER_CA_PENDING"

SETTINGS_MENU = "SETTINGS_MENU"

HANDLED_STATES = {
    CHANGE_NUMBER_START,
    CHANGE_NUMBER_CONFIRM_EMAIL,
    CHANGE_NUMBER_ENTER_OTP,
    CHANGE_NUMBER_SUCCESS,
    CHANGE_NUMBER_LOCKED,
    CHANGE_NUMBER_CA_VERIFY,
    CHANGE_NUMBER_CA_PENDING,
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
    """Handle mobile number change states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    data = session.setdefault("data", {})

    # ── CHANGE_NUMBER_START ──────────────────────────────────
    if state == CHANGE_NUMBER_START:
        from app.domain.services.otp_service import is_locked

        if is_locked(wa_id):
            session["state"] = CHANGE_NUMBER_LOCKED
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CHANGE_NUMBER_LOCKED"))
            return Response(status_code=200)

        choice = text.strip()

        if choice == "1":
            # Email OTP path
            session["state"] = CHANGE_NUMBER_CONFIRM_EMAIL
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CHANGE_NUMBER_ASK_EMAIL"))
            return Response(status_code=200)

        if choice == "2":
            # CA verification path
            session["state"] = CHANGE_NUMBER_CA_VERIFY
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CHANGE_NUMBER_CA_UPLOAD"))
            return Response(status_code=200)

        # Show options
        await send(wa_id, t(session, "CHANGE_NUMBER_START"))
        return Response(status_code=200)

    # ── CHANGE_NUMBER_CONFIRM_EMAIL ──────────────────────────
    if state == CHANGE_NUMBER_CONFIRM_EMAIL:
        email = text.strip().lower()

        # Basic email validation
        if "@" not in email or "." not in email:
            await send(wa_id, t(session, "CHANGE_NUMBER_INVALID_EMAIL"))
            return Response(status_code=200)

        data["change_number_email"] = email

        # Generate and "send" OTP
        from app.domain.services.otp_service import generate_otp, send_otp_email

        otp = generate_otp(wa_id, "change_number")
        lang = session.get("lang", "en")

        try:
            await send_otp_email(email, otp, lang)
        except NotImplementedError:
            # Prod: email not implemented, fallback to CA path
            await send(wa_id, t(session, "CHANGE_NUMBER_EMAIL_NOT_AVAILABLE"))
            session["state"] = CHANGE_NUMBER_CA_VERIFY
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CHANGE_NUMBER_CA_UPLOAD"))
            return Response(status_code=200)

        session["state"] = CHANGE_NUMBER_ENTER_OTP
        await session_cache.save_session(wa_id, session)
        from app.domain.services.pii_masking import mask_email
        await send(wa_id, t(session, "CHANGE_NUMBER_OTP_SENT",
                            email=mask_email(email)))
        return Response(status_code=200)

    # ── CHANGE_NUMBER_ENTER_OTP ──────────────────────────────
    if state == CHANGE_NUMBER_ENTER_OTP:
        code = text.strip()

        from app.domain.services.otp_service import verify_otp, is_locked

        if is_locked(wa_id):
            session["state"] = CHANGE_NUMBER_LOCKED
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CHANGE_NUMBER_LOCKED"))
            return Response(status_code=200)

        if verify_otp(wa_id, "change_number", code):
            session["state"] = CHANGE_NUMBER_SUCCESS
            data["number_change_verified"] = True
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CHANGE_NUMBER_SUCCESS"))
            return Response(status_code=200)

        # Invalid OTP
        await send(wa_id, t(session, "CHANGE_NUMBER_INVALID_OTP"))
        return Response(status_code=200)

    # ── CHANGE_NUMBER_SUCCESS ────────────────────────────────
    if state == CHANGE_NUMBER_SUCCESS:
        # Any input → back to settings
        session["state"] = SETTINGS_MENU
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "SETTINGS_MENU"))
        return Response(status_code=200)

    # ── CHANGE_NUMBER_LOCKED ─────────────────────────────────
    if state == CHANGE_NUMBER_LOCKED:
        # Any input → back to settings
        session["state"] = SETTINGS_MENU
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "SETTINGS_MENU"))
        return Response(status_code=200)

    # ── CHANGE_NUMBER_CA_VERIFY ──────────────────────────────
    if state == CHANGE_NUMBER_CA_VERIFY:
        # This state shows upload prompt. If user sends text, remind them.
        # Actual document upload is handled in whatsapp.py
        await send(wa_id, t(session, "CHANGE_NUMBER_CA_UPLOAD"))
        return Response(status_code=200)

    # ── CHANGE_NUMBER_CA_PENDING ─────────────────────────────
    if state == CHANGE_NUMBER_CA_PENDING:
        # Any input → back to settings
        session["state"] = SETTINGS_MENU
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "SETTINGS_MENU"))
        return Response(status_code=200)

    return None
