# tests/test_settings_handler.py
"""Tests for settings_handler — Language, Profile, Segment view, Change Number."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.wa_handlers import settings_handler


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _make_handler_kwargs(session):
    """Build the kwargs dict expected by each handler's handle()."""
    mock_cache = MagicMock()
    mock_cache.save_session = AsyncMock()

    return dict(
        session_cache=mock_cache,
        send=AsyncMock(),
        send_buttons=AsyncMock(),
        send_menu_result=AsyncMock(),
        t=lambda s, key, **kw: f"[{key}]",
        push_state=lambda s, st: s.setdefault("_state_stack", []).append(st),
        pop_state=lambda s: s.get("_state_stack", ["MAIN_MENU"]).pop() if s.get("_state_stack") else "MAIN_MENU",
        state_to_screen_key=lambda st: st,
        get_lang=lambda s: s.get("data", {}).get("lang", "en"),
    )


WA_ID = "919999999999"


# ── 1. SETTINGS_MENU "1" → LANG_MENU ───────────────────────────

def test_settings_menu_language(event_loop):
    """Choosing '1' (Language) should push SETTINGS_MENU and transition to LANG_MENU."""
    session = {"state": "SETTINGS_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("SETTINGS_MENU", "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "LANG_MENU"
    assert "SETTINGS_MENU" in session["_state_stack"]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[LANG_MENU]")
    kwargs["session_cache"].save_session.assert_awaited_once()


# ── 2. SETTINGS_MENU "2" → SETTINGS_PROFILE (masked GSTIN) ─────

@patch(
    "app.api.routes.wa_handlers.settings_handler.mask_gstin_display",
    side_effect=lambda g: "XXXX" + g[-4:],
    create=True,
)
def test_settings_menu_profile(mock_mask, event_loop):
    """Choosing '2' (Profile) should show profile with masked GSTIN."""
    session = {
        "state": "SETTINGS_MENU",
        "data": {"gstin": "36AABCU9603R1ZM", "business_name": "Acme Corp"},
        "lang": "en",
    }
    kwargs = _make_handler_kwargs(session)

    with patch(
        "app.domain.services.pii_masking.mask_gstin_display",
        side_effect=lambda g: "XXXX" + g[-4:],
    ), patch(
        "app.domain.services.pii_masking.mask_email",
        side_effect=lambda e: "***@***.com",
    ):
        result = event_loop.run_until_complete(
            settings_handler.handle("SETTINGS_MENU", "2", WA_ID, session, **kwargs)
        )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "SETTINGS_PROFILE"
    assert "SETTINGS_MENU" in session["_state_stack"]
    kwargs["session_cache"].save_session.assert_awaited_once()
    # send should have been called for the profile display
    assert kwargs["send"].await_count >= 1


# ── 3. SETTINGS_MENU "3" → SETTINGS_SEGMENT_VIEW ───────────────

def test_settings_menu_view_segment(event_loop):
    """Choosing '3' (View Segment) should transition to SETTINGS_SEGMENT_VIEW."""
    session = {"state": "SETTINGS_MENU", "data": {"client_segment": "medium"}, "lang": "en"}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("SETTINGS_MENU", "3", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "SETTINGS_SEGMENT_VIEW"
    assert "SETTINGS_MENU" in session["_state_stack"]
    kwargs["session_cache"].save_session.assert_awaited_once()
    assert kwargs["send"].await_count >= 1


# ── 4. SETTINGS_MENU "4" → CHANGE_NUMBER_START ─────────────────

def test_settings_menu_change_number(event_loop):
    """Choosing '4' (Change Number) should transition to CHANGE_NUMBER_START."""
    session = {"state": "SETTINGS_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("SETTINGS_MENU", "4", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "CHANGE_NUMBER_START"
    assert "SETTINGS_MENU" in session["_state_stack"]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_START]")
    kwargs["session_cache"].save_session.assert_awaited_once()


# ── 5. SETTINGS_MENU invalid input → re-shows settings menu ────

def test_settings_menu_invalid_input(event_loop):
    """Invalid input should re-show the settings menu without state change."""
    session = {"state": "SETTINGS_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("SETTINGS_MENU", "garbage", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should remain SETTINGS_MENU (handler doesn't change it for invalid)
    assert session["state"] == "SETTINGS_MENU"
    kwargs["send"].assert_awaited_once_with(WA_ID, "[SETTINGS_MENU]")
    # save_session should NOT be called for invalid input
    kwargs["session_cache"].save_session.assert_not_awaited()


# ── 6. SETTINGS_PROFILE — any text → pops state back ───────────

def test_settings_profile_pops_state(event_loop):
    """Any text in SETTINGS_PROFILE should pop back to the previous state."""
    session = {
        "state": "SETTINGS_PROFILE",
        "data": {},
        "_state_stack": ["SETTINGS_MENU"],
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("SETTINGS_PROFILE", "ok", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "SETTINGS_MENU"
    assert session["_state_stack"] == []
    kwargs["session_cache"].save_session.assert_awaited_once()
    kwargs["send"].assert_awaited_once_with(WA_ID, "[SETTINGS_MENU]")


# ── 7. SETTINGS_SEGMENT_VIEW "1" → logs request, returns ───────

def test_settings_segment_view_request_change(event_loop):
    """Choosing '1' in segment view should log request and pop back."""
    session = {
        "state": "SETTINGS_SEGMENT_VIEW",
        "data": {},
        "_state_stack": ["SETTINGS_MENU"],
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("SETTINGS_SEGMENT_VIEW", "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "SETTINGS_MENU"
    assert session["_state_stack"] == []
    # Two send calls: SEGMENT_CHANGE_REQUESTED + popped-state screen
    assert kwargs["send"].await_count == 2
    kwargs["session_cache"].save_session.assert_awaited_once()


# ── 8. SETTINGS_SEGMENT_VIEW other → returns to previous state ──

def test_settings_segment_view_other_input(event_loop):
    """Non-'1' input in segment view should just pop back without logging."""
    session = {
        "state": "SETTINGS_SEGMENT_VIEW",
        "data": {},
        "_state_stack": ["SETTINGS_MENU"],
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("SETTINGS_SEGMENT_VIEW", "back", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "SETTINGS_MENU"
    # Only one send call (the popped-state screen)
    assert kwargs["send"].await_count == 1
    kwargs["session_cache"].save_session.assert_awaited_once()


# ── 9. Unhandled state returns None ─────────────────────────────

def test_unhandled_state_returns_none(event_loop):
    """Handler should return None for states it doesn't handle."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        settings_handler.handle("MAIN_MENU", "hi", WA_ID, session, **kwargs)
    )

    assert result is None
