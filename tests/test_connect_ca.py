# tests/test_connect_ca.py
"""Tests for the Connect with CA WhatsApp handler."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.wa_handlers import connect_ca
from app.api.routes.wa_handlers.connect_ca import (
    CONNECT_CA_MENU,
    CONNECT_CA_ASK_TEXT,
    CONNECT_CA_CALL_TIME,
    CONNECT_CA_SHARE_DOCS,
)

WA_ID = "919999999999"


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


# ── CONNECT_CA_MENU ────────────────────────────────────────────


def test_menu_choice_1_ask_question(event_loop):
    """Menu choice '1' should transition to CONNECT_CA_ASK_TEXT."""
    session = {"state": CONNECT_CA_MENU, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_MENU, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CONNECT_CA_ASK_TEXT
    # State stack should have CONNECT_CA_MENU pushed (for back navigation)
    assert session["_state_stack"] == [CONNECT_CA_MENU]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CA_ASK_QUESTION_PROMPT]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


def test_menu_choice_2_request_call(event_loop):
    """Menu choice '2' should transition to CONNECT_CA_CALL_TIME."""
    session = {"state": CONNECT_CA_MENU, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_MENU, "2", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CONNECT_CA_CALL_TIME
    assert session["_state_stack"] == [CONNECT_CA_MENU]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CA_CALL_TIME_PROMPT]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


def test_menu_choice_3_share_docs(event_loop):
    """Menu choice '3' should transition to CONNECT_CA_SHARE_DOCS."""
    session = {"state": CONNECT_CA_MENU, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_MENU, "3", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CONNECT_CA_SHARE_DOCS
    assert session["_state_stack"] == [CONNECT_CA_MENU]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CA_SHARE_DOCS_PROMPT]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


def test_menu_invalid_input_reshows_menu(event_loop):
    """Invalid menu input should re-show the CONNECT_CA_MENU prompt."""
    session = {"state": CONNECT_CA_MENU, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_MENU, "99", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should remain unchanged (no transition)
    assert session["state"] == CONNECT_CA_MENU
    # No state stack push for invalid input
    assert "_state_stack" not in session
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CONNECT_CA_MENU]")
    kwargs["session_cache"].save_session.assert_not_awaited()


# ── CONNECT_CA_ASK_TEXT ─────────────────────────────────────────


def test_ask_text_valid_question(event_loop):
    """A question with >= 3 chars should be stored and confirmed."""
    session = {"state": CONNECT_CA_ASK_TEXT, "data": {}}
    kwargs = _make_handler_kwargs(session)

    question = "What is the deadline for GST filing this quarter?"
    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_ASK_TEXT, question, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # Should return to menu after storing
    assert session["state"] == CONNECT_CA_MENU
    # Question should be appended to ca_questions list
    assert session["data"]["ca_questions"] == [question]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CA_QUESTION_RECEIVED]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


def test_ask_text_too_short(event_loop):
    """A question shorter than 3 chars should show an error message."""
    session = {"state": CONNECT_CA_ASK_TEXT, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_ASK_TEXT, "hi", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should NOT change — user stays in ASK_TEXT to retry
    assert session["state"] == CONNECT_CA_ASK_TEXT
    # No question stored
    assert "ca_questions" not in session.get("data", {})
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CA_ASK_QUESTION_TOO_SHORT]")
    kwargs["session_cache"].save_session.assert_not_awaited()


# ── CONNECT_CA_CALL_TIME ────────────────────────────────────────


@pytest.mark.parametrize(
    "choice,expected_slot",
    [("1", "morning"), ("2", "afternoon"), ("3", "evening")],
)
def test_call_time_valid_choices(event_loop, choice, expected_slot):
    """Valid time-slot choices 1/2/3 should store preference and confirm."""
    session = {"state": CONNECT_CA_CALL_TIME, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_CALL_TIME, choice, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # Should return to menu
    assert session["state"] == CONNECT_CA_MENU
    assert session["data"]["ca_callback_time"] == expected_slot
    kwargs["send"].assert_awaited_once_with(
        WA_ID, f"[CA_CALL_REQUESTED]"
    )
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


def test_call_time_invalid_choice(event_loop):
    """Invalid call-time input should re-show the time prompt."""
    session = {"state": CONNECT_CA_CALL_TIME, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(CONNECT_CA_CALL_TIME, "5", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State unchanged
    assert session["state"] == CONNECT_CA_CALL_TIME
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CA_CALL_TIME_PROMPT]")
    kwargs["session_cache"].save_session.assert_not_awaited()


# ── CONNECT_CA_SHARE_DOCS ──────────────────────────────────────


def test_share_docs_text_input_shows_upload_reminder(event_loop):
    """Text input in SHARE_DOCS state should remind user to upload a file."""
    session = {"state": CONNECT_CA_SHARE_DOCS, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle(
            CONNECT_CA_SHARE_DOCS,
            "here is my document",
            WA_ID,
            session,
            **kwargs,
        )
    )

    assert result is not None
    assert result.status_code == 200
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CA_SHARE_DOCS_PROMPT]")


# ── Unhandled state ─────────────────────────────────────────────


def test_unhandled_state_returns_none(event_loop):
    """A state not in HANDLED_STATES should return None."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        connect_ca.handle("MAIN_MENU", "hi", WA_ID, session, **kwargs)
    )

    assert result is None
    kwargs["send"].assert_not_awaited()
    kwargs["session_cache"].save_session.assert_not_awaited()
