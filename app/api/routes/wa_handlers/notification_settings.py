# app/api/routes/wa_handlers/notification_settings.py
"""Notification settings handler (Phase 10).

States handled:
    NOTIFICATION_SETTINGS
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.notification_settings")

# State constants
NOTIFICATION_SETTINGS = "NOTIFICATION_SETTINGS"
SETTINGS_MENU = "SETTINGS_MENU"

HANDLED_STATES = {NOTIFICATION_SETTINGS}


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
    """Handle notification preferences states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    if state == NOTIFICATION_SETTINGS:
        pref_map = {
            "1": {"filing_reminders": True, "risk_alerts": False, "status_updates": False},
            "2": {"filing_reminders": False, "risk_alerts": True, "status_updates": False},
            "3": {"filing_reminders": False, "risk_alerts": False, "status_updates": True},
            "4": {"filing_reminders": True, "risk_alerts": True, "status_updates": True},
            "5": {"filing_reminders": False, "risk_alerts": False, "status_updates": False},
        }
        if text in pref_map:
            session.setdefault("data", {})["notification_prefs"] = pref_map[text]
            await session_cache.save_session(wa_id, session)
            if text == "5":
                await send(wa_id, "🔕 Notifications turned off.\n\nMENU = Main Menu\nBACK = Go Back")
            else:
                await send(
                    wa_id, "🔔 Notification preferences updated!\n\nMENU = Main Menu\nBACK = Go Back"
                )
            session["state"] = SETTINGS_MENU
            await session_cache.save_session(wa_id, session)
        else:
            await send(wa_id, t(session, "NOTIFICATION_SETTINGS"))
        return Response(status_code=200)

    return None
