# app/api/routes/wa_handlers/gst_onboarding.py
"""
GST Onboarding handler — 6-step guided flow for new GST users.

Steps:
  1. GST_START_GSTIN     — enter GSTIN (or reuse saved)
  2. GST_GSTIN_CONFIRM   — confirm business name / state / status
  3. GST_FILING_FREQUENCY — monthly / quarterly / composition
  4. GST_TURNOVER_BAND   — approx yearly turnover band
  5. GST_MULTI_GST_CHECK — single or multiple GSTINs?
  5b. GST_MULTI_GST_ADD  — enter additional GSTINs
  6. GST_SEGMENT_DONE    — show detected segment, proceed to GST menu

Side effects:
  Stores gstin, business_name, filing_mode, turnover_band, multi_gstin,
  additional_gstins, client_segment, gst_onboarded in session["data"].
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.gst_onboarding")

# State constants
GST_START_GSTIN = "GST_START_GSTIN"
GST_GSTIN_CONFIRM = "GST_GSTIN_CONFIRM"
GST_FILING_FREQUENCY = "GST_FILING_FREQUENCY"
GST_TURNOVER_BAND = "GST_TURNOVER_BAND"
GST_MULTI_GST_CHECK = "GST_MULTI_GST_CHECK"
GST_MULTI_GST_ADD = "GST_MULTI_GST_ADD"
GST_SEGMENT_DONE = "GST_SEGMENT_DONE"

GST_MENU = "GST_MENU"

HANDLED_STATES = {
    GST_START_GSTIN,
    GST_GSTIN_CONFIRM,
    GST_FILING_FREQUENCY,
    GST_TURNOVER_BAND,
    GST_MULTI_GST_CHECK,
    GST_MULTI_GST_ADD,
    GST_SEGMENT_DONE,
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
    """Handle GST onboarding flow states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    data = session.setdefault("data", {})

    # ── Step 1: Enter GSTIN ──────────────────────────────────────
    if state == GST_START_GSTIN:
        return await _handle_start_gstin(text, wa_id, session, data,
                                         session_cache=session_cache, send=send,
                                         send_buttons=send_buttons, t=t)

    # ── Step 2: Confirm business details ─────────────────────────
    if state == GST_GSTIN_CONFIRM:
        return await _handle_gstin_confirm(text, wa_id, session, data,
                                           session_cache=session_cache, send=send, t=t)

    # ── Step 3: Filing frequency ─────────────────────────────────
    if state == GST_FILING_FREQUENCY:
        return await _handle_filing_frequency(text, wa_id, session, data,
                                              session_cache=session_cache, send=send, t=t)

    # ── Step 4: Turnover band ────────────────────────────────────
    if state == GST_TURNOVER_BAND:
        return await _handle_turnover_band(text, wa_id, session, data,
                                           session_cache=session_cache, send=send, t=t)

    # ── Step 5: Multi-GST check ──────────────────────────────────
    if state == GST_MULTI_GST_CHECK:
        return await _handle_multi_gst_check(text, wa_id, session, data,
                                             session_cache=session_cache, send=send, t=t)

    # ── Step 5b: Add additional GSTINs ───────────────────────────
    if state == GST_MULTI_GST_ADD:
        return await _handle_multi_gst_add(text, wa_id, session, data,
                                           session_cache=session_cache, send=send, t=t)

    # ── Step 6: Segment done — proceed ───────────────────────────
    if state == GST_SEGMENT_DONE:
        return await _handle_segment_done(text, wa_id, session, data,
                                          session_cache=session_cache, send=send,
                                          send_menu_result=send_menu_result, t=t)

    return None


# ══════════════════════════════════════════════════════════════════
# Step handlers
# ══════════════════════════════════════════════════════════════════

async def _handle_start_gstin(
    text: str, wa_id: str, session: dict, data: dict, *,
    session_cache, send, send_buttons, t,
) -> Response:
    """Step 1: User enters GSTIN."""
    from app.domain.services.gstin_pan_validation import is_valid_gstin

    gstin = text.strip().upper()

    if not is_valid_gstin(gstin):
        await send(wa_id, t(session, "INVALID_GSTIN"))
        return Response(status_code=200)

    data["gstin"] = gstin

    # Try looking up business details from API
    details = await _lookup_gstin_safe(gstin)

    if details and details.get("legal_name"):
        data["business_name"] = details["legal_name"]
        data["gstin_state"] = details.get("state", "")
        data["gstin_status"] = details.get("status", "")

        # Show confirmation
        session["state"] = GST_GSTIN_CONFIRM
        await session_cache.save_session(wa_id, session)
        await send(
            wa_id,
            t(session, "GST_ONBOARD_CONFIRM",
              business_name=details["legal_name"],
              state=details.get("state", "N/A"),
              status=details.get("status", "N/A")),
        )
    else:
        # API not available — skip confirmation, go to filing frequency
        data["business_name"] = ""
        session["state"] = GST_FILING_FREQUENCY
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "GST_ONBOARD_FREQUENCY"))

    return Response(status_code=200)


async def _handle_gstin_confirm(
    text: str, wa_id: str, session: dict, data: dict, *,
    session_cache, send, t,
) -> Response:
    """Step 2: Confirm business details. Yes → next, Re-enter → back to step 1."""
    choice = text.strip().lower()

    if choice in ("1", "yes", "y"):
        # Confirmed — proceed to filing frequency
        session["state"] = GST_FILING_FREQUENCY
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "GST_ONBOARD_FREQUENCY"))
        return Response(status_code=200)

    if choice in ("2", "no", "n", "re-enter", "change"):
        # Re-enter GSTIN
        data.pop("gstin", None)
        data.pop("business_name", None)
        session["state"] = GST_START_GSTIN
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "GST_ONBOARD_ASK_GSTIN"))
        return Response(status_code=200)

    # Invalid
    await send(wa_id, t(session, "GST_ONBOARD_CONFIRM_INVALID"))
    return Response(status_code=200)


async def _handle_filing_frequency(
    text: str, wa_id: str, session: dict, data: dict, *,
    session_cache, send, t,
) -> Response:
    """Step 3: Filing frequency — 1=Monthly, 2=Quarterly, 3=Composition."""
    choice = text.strip()

    frequency_map = {"1": "monthly", "2": "quarterly", "3": "composition"}
    if choice not in frequency_map:
        await send(wa_id, t(session, "GST_ONBOARD_FREQUENCY"))
        return Response(status_code=200)

    data["filing_mode"] = frequency_map[choice]

    session["state"] = GST_TURNOVER_BAND
    await session_cache.save_session(wa_id, session)
    await send(wa_id, t(session, "GST_ONBOARD_TURNOVER"))
    return Response(status_code=200)


async def _handle_turnover_band(
    text: str, wa_id: str, session: dict, data: dict, *,
    session_cache, send, t,
) -> Response:
    """Step 4: Turnover band — 1=Below 5Cr, 2=5-50Cr, 3=Above 50Cr."""
    choice = text.strip()

    band_map = {"1": "below_5cr", "2": "5_to_50cr", "3": "above_50cr"}
    if choice not in band_map:
        await send(wa_id, t(session, "GST_ONBOARD_TURNOVER"))
        return Response(status_code=200)

    data["turnover_band"] = band_map[choice]

    session["state"] = GST_MULTI_GST_CHECK
    await session_cache.save_session(wa_id, session)
    await send(wa_id, t(session, "GST_ONBOARD_MULTI_CHECK"))
    return Response(status_code=200)


async def _handle_multi_gst_check(
    text: str, wa_id: str, session: dict, data: dict, *,
    session_cache, send, t,
) -> Response:
    """Step 5: Multi-GSTIN check — 1=No (single), 2=Yes (multiple)."""
    choice = text.strip().lower()

    if choice in ("1", "no", "n"):
        data["multi_gstin"] = False
        data["additional_gstins"] = []
        # Compute segment and finish
        return await _finish_onboarding(wa_id, session, data,
                                        session_cache=session_cache, send=send, t=t)

    if choice in ("2", "yes", "y"):
        data["multi_gstin"] = True
        data.setdefault("additional_gstins", [])
        session["state"] = GST_MULTI_GST_ADD
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "GST_ONBOARD_MULTI_ADD"))
        return Response(status_code=200)

    # Invalid
    await send(wa_id, t(session, "GST_ONBOARD_MULTI_CHECK"))
    return Response(status_code=200)


async def _handle_multi_gst_add(
    text: str, wa_id: str, session: dict, data: dict, *,
    session_cache, send, t,
) -> Response:
    """Step 5b: Add additional GSTINs one by one, or DONE to finish."""
    from app.domain.services.gstin_pan_validation import is_valid_gstin

    stripped = text.strip().upper()

    if stripped == "DONE":
        return await _finish_onboarding(wa_id, session, data,
                                        session_cache=session_cache, send=send, t=t)

    if not is_valid_gstin(stripped):
        await send(wa_id, t(session, "INVALID_GSTIN"))
        await send(wa_id, t(session, "GST_ONBOARD_MULTI_ADD"))
        return Response(status_code=200)

    additional = data.setdefault("additional_gstins", [])
    if stripped not in additional and stripped != data.get("gstin"):
        additional.append(stripped)

    count = len(additional)
    await send(
        wa_id,
        t(session, "GST_ONBOARD_MULTI_ADDED", count=count, gstin=stripped),
    )
    return Response(status_code=200)


async def _handle_segment_done(
    text: str, wa_id: str, session: dict, data: dict, *,
    session_cache, send, send_menu_result, t,
) -> Response:
    """Step 6: Segment shown — user picks Open GST Menu or Main Menu."""
    choice = text.strip()

    if choice == "1":
        # Open GST menu
        session["state"] = GST_MENU
        await session_cache.save_session(wa_id, session)
        # Build and send the segment-aware GST menu
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

    if choice == "2":
        # Main menu
        session["state"] = "MAIN_MENU"
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "WELCOME_MENU"))
        return Response(status_code=200)

    # Invalid — re-show
    segment_label = _segment_display_label(data.get("client_segment", "small"), session)
    await send(wa_id, t(session, "GST_ONBOARD_DONE", segment=segment_label))
    return Response(status_code=200)


# ══════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════

async def _finish_onboarding(
    wa_id: str, session: dict, data: dict, *,
    session_cache, send, t,
) -> Response:
    """Compute segment from onboarding data and show result."""
    from app.domain.services.segment_detection import detect_segment

    # Map turnover band to numeric value for segment detection
    _TURNOVER_MAP = {
        "below_5cr": 2_00_00_000,      # 2 Cr (below threshold)
        "5_to_50cr": 20_00_00_000,     # 20 Cr (medium)
        "above_50cr": 60_00_00_000,    # 60 Cr (enterprise)
    }
    turnover = _TURNOVER_MAP.get(data.get("turnover_band", ""), 0)
    gstin_count = 1 + len(data.get("additional_gstins", []))

    segment = detect_segment(
        annual_turnover=turnover,
        gstin_count=gstin_count,
    )

    data["client_segment"] = segment
    data["gst_onboarded"] = True

    session["state"] = GST_SEGMENT_DONE
    await session_cache.save_session(wa_id, session)

    segment_label = _segment_display_label(segment, session)
    await send(wa_id, t(session, "GST_ONBOARD_DONE", segment=segment_label))
    return Response(status_code=200)


def _segment_display_label(segment: str, session: dict) -> str:
    """Map internal segment code to user-facing label.

    Keep 'enterprise' in code, display as 'Large' per user spec.
    """
    lang = session.get("lang", "en")
    _LABELS = {
        "en": {"small": "Small", "medium": "Medium", "enterprise": "Large"},
        "hi": {"small": "छोटा", "medium": "मध्यम", "enterprise": "बड़ा"},
        "gu": {"small": "નાનું", "medium": "મધ્યમ", "enterprise": "મોટું"},
        "ta": {"small": "சிறியது", "medium": "நடுத்தரம்", "enterprise": "பெரியது"},
        "te": {"small": "చిన్నది", "medium": "మధ్యస్థం", "enterprise": "పెద్దది"},
        "kn": {"small": "ಚಿಕ್ಕದು", "medium": "ಮಧ್ಯಮ", "enterprise": "ದೊಡ್ಡದು"},
    }
    lang_labels = _LABELS.get(lang, _LABELS["en"])
    return lang_labels.get(segment, segment)


async def _lookup_gstin_safe(gstin: str):
    """Attempt GSTIN lookup, return None on any error."""
    try:
        from app.domain.services.gstin_lookup import lookup_gstin_details
        return await lookup_gstin_details(gstin)
    except Exception:
        logger.debug("gstin_lookup failed for %s", gstin, exc_info=True)
        return None
