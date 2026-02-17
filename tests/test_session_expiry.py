# tests/test_session_expiry.py
"""Tests for the session expiry handler (wa_handlers/session_expiry)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.wa_handlers import session_expiry


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


# ── SESSION_RESUME_PROMPT ────────────────────────────────


def test_resume_prompt_continue_restores_pre_expiry_state(event_loop):
    """Option '1' (Continue) should restore the pre_expiry_state."""
    session = {
        "state": "SESSION_RESUME_PROMPT",
        "data": {"pre_expiry_state": "GST_UPLOAD"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("SESSION_RESUME_PROMPT", "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_UPLOAD"
    assert "pre_expiry_state" not in session["data"]
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_UPLOAD]")


def test_resume_prompt_start_over_clears_data_and_goes_to_module_menu(event_loop):
    """Option '2' (Start Over) should clear flow data and go to the module menu."""
    session = {
        "state": "SESSION_RESUME_PROMPT",
        "data": {
            "pre_expiry_state": "GST_FILING_CONFIRM",
            "gstin": "36AABCU9603R1ZM",
            "wizard_step": 3,
            "gst_filing_period": "2024-01",
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("SESSION_RESUME_PROMPT", "2", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # GST_FILING_CONFIRM starts with GST_ so module menu is GST_MENU
    assert session["state"] == "GST_MENU"
    assert "pre_expiry_state" not in session["data"]
    # Persistent keys should be kept
    assert session["data"]["gstin"] == "36AABCU9603R1ZM"
    # Transient flow keys should be cleared
    assert "wizard_step" not in session["data"]
    assert "gst_filing_period" not in session["data"]
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_MENU]")


def test_resume_prompt_start_over_itr_module(event_loop):
    """Option '2' for an ITR state should go to ITR_MENU."""
    session = {
        "state": "SESSION_RESUME_PROMPT",
        "data": {"pre_expiry_state": "ITR1_UPLOAD"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("SESSION_RESUME_PROMPT", "2", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "ITR_MENU"


def test_resume_prompt_main_menu(event_loop):
    """Option '3' (Main Menu) should clear data and go to MAIN_MENU."""
    session = {
        "state": "SESSION_RESUME_PROMPT",
        "data": {
            "pre_expiry_state": "GST_UPLOAD",
            "wizard_step": 5,
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("SESSION_RESUME_PROMPT", "3", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "MAIN_MENU"
    assert "pre_expiry_state" not in session["data"]
    assert "wizard_step" not in session["data"]
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    kwargs["send"].assert_awaited_once_with(WA_ID, "[WELCOME_MENU]")


def test_resume_prompt_invalid_input_reshows_prompt(event_loop):
    """Invalid input should re-show the SESSION_RESUME_PROMPT screen."""
    session = {
        "state": "SESSION_RESUME_PROMPT",
        "data": {"pre_expiry_state": "GST_UPLOAD"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("SESSION_RESUME_PROMPT", "banana", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should NOT change — still on the prompt
    assert session["state"] == "SESSION_RESUME_PROMPT"
    # pre_expiry_state should remain so the user can still choose
    assert session["data"]["pre_expiry_state"] == "GST_UPLOAD"
    # save_session should NOT be called for invalid input
    kwargs["session_cache"].save_session.assert_not_awaited()
    kwargs["send"].assert_awaited_once_with(WA_ID, "[SESSION_RESUME_PROMPT]")


# ── SENSITIVE_CONFIRM_EXPIRED ────────────────────────────


def test_sensitive_expired_any_input_restores_pre_expiry_state(event_loop):
    """Any input on SENSITIVE_CONFIRM_EXPIRED should restore the pre_expiry_state."""
    session = {
        "state": "SENSITIVE_CONFIRM_EXPIRED",
        "data": {"pre_expiry_state": "GST_FILING_CONFIRM"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("SENSITIVE_CONFIRM_EXPIRED", "anything", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_FILING_CONFIRM"
    assert "pre_expiry_state" not in session["data"]
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_FILING_CONFIRM]")


def test_sensitive_expired_defaults_to_main_menu_when_no_pre_state(event_loop):
    """When pre_expiry_state is missing, fall back to MAIN_MENU."""
    session = {
        "state": "SENSITIVE_CONFIRM_EXPIRED",
        "data": {},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("SENSITIVE_CONFIRM_EXPIRED", "ok", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "MAIN_MENU"
    kwargs["send"].assert_awaited_once_with(WA_ID, "[MAIN_MENU]")


# ── Unhandled states ─────────────────────────────────────


def test_unhandled_state_returns_none(event_loop):
    """States not in HANDLED_STATES should return None."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        session_expiry.handle("MAIN_MENU", "hi", WA_ID, session, **kwargs)
    )

    assert result is None
    kwargs["send"].assert_not_awaited()
    kwargs["session_cache"].save_session.assert_not_awaited()
