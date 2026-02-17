# app/api/routes/wa_handlers/module_switch.py
"""
Cross-module switch handler.

State handled:
    CONFIRM_SWITCH_MODULE — user wants to switch between GST/ITR while in a flow
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.module_switch")

# State constants
CONFIRM_SWITCH_MODULE = "CONFIRM_SWITCH_MODULE"

MAIN_MENU = "MAIN_MENU"
GST_MENU = "GST_MENU"
ITR_MENU = "ITR_MENU"

HANDLED_STATES = {
    CONFIRM_SWITCH_MODULE,
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
    """Handle module switch confirmation. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    choice = text.strip()
    data = session.setdefault("data", {})
    target_module = data.get("switch_target_module", MAIN_MENU)

    if choice == "1":
        # Switch — go to target module
        session["state"] = target_module
        data.pop("switch_target_module", None)
        data.pop("switch_source_module", None)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, state_to_screen_key(target_module)))
        return Response(status_code=200)

    if choice == "2":
        # Stay — go back to where we were
        prev_state = data.get("switch_source_module", MAIN_MENU)
        session["state"] = prev_state
        data.pop("switch_target_module", None)
        data.pop("switch_source_module", None)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, state_to_screen_key(prev_state)))
        return Response(status_code=200)

    # Invalid — re-show
    source_label = _module_label(data.get("switch_source_module", ""), session)
    target_label = _module_label(target_module, session)
    await send(wa_id, t(session, "CONFIRM_SWITCH_MODULE",
                        current_module=source_label,
                        target_module=target_label))
    return Response(status_code=200)


def _module_label(module_state: str, session: dict) -> str:
    """Get a user-friendly label for a module state."""
    _LABELS = {
        "GST_MENU": "GST",
        "ITR_MENU": "ITR",
        "CONNECT_CA_MENU": "Connect with CA",
        "SETTINGS_MENU": "Settings",
    }
    return _LABELS.get(module_state, module_state)
