# tests/test_change_number.py
"""Tests for the mobile number change handler (wa_handlers/change_number.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.wa_handlers import change_number
from app.api.routes.wa_handlers.change_number import (
    CHANGE_NUMBER_CA_PENDING,
    CHANGE_NUMBER_CA_VERIFY,
    CHANGE_NUMBER_CONFIRM_EMAIL,
    CHANGE_NUMBER_ENTER_OTP,
    CHANGE_NUMBER_LOCKED,
    CHANGE_NUMBER_START,
    CHANGE_NUMBER_SUCCESS,
    SETTINGS_MENU,
)


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
        pop_state=lambda s: s.get("_state_stack", ["MAIN_MENU"]).pop()
        if s.get("_state_stack")
        else "MAIN_MENU",
        state_to_screen_key=lambda st: st,
        get_lang=lambda s: s.get("data", {}).get("lang", "en"),
    )


WA_ID = "919999999999"


# ── 1. CHANGE_NUMBER_START — "1" → CHANGE_NUMBER_CONFIRM_EMAIL ──────


@patch("app.domain.services.otp_service.is_locked", return_value=False)
def test_start_choice_1_email_path(mock_is_locked, event_loop):
    """Choosing '1' at START should transition to CONFIRM_EMAIL."""
    session = {"state": CHANGE_NUMBER_START, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(CHANGE_NUMBER_START, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CHANGE_NUMBER_CONFIRM_EMAIL
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_ASK_EMAIL]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    mock_is_locked.assert_called_once_with(WA_ID)


# ── 2. CHANGE_NUMBER_START — "2" → CHANGE_NUMBER_CA_VERIFY ──────────


@patch("app.domain.services.otp_service.is_locked", return_value=False)
def test_start_choice_2_ca_path(mock_is_locked, event_loop):
    """Choosing '2' at START should transition to CA_VERIFY."""
    session = {"state": CHANGE_NUMBER_START, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(CHANGE_NUMBER_START, "2", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CHANGE_NUMBER_CA_VERIFY
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_CA_UPLOAD]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    mock_is_locked.assert_called_once_with(WA_ID)


# ── 3. CHANGE_NUMBER_START — locked user → CHANGE_NUMBER_LOCKED ─────


@patch("app.domain.services.otp_service.is_locked", return_value=True)
def test_start_locked_user(mock_is_locked, event_loop):
    """A locked user at START should transition to LOCKED."""
    session = {"state": CHANGE_NUMBER_START, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(CHANGE_NUMBER_START, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CHANGE_NUMBER_LOCKED
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_LOCKED]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    mock_is_locked.assert_called_once_with(WA_ID)


# ── 4. CHANGE_NUMBER_CONFIRM_EMAIL — valid email → OTP sent ─────────


@patch("app.domain.services.pii_masking.mask_email", return_value="su\u2022\u2022\u2022\u2022@gmail.com")
@patch("app.domain.services.otp_service.send_otp_email", new_callable=AsyncMock, return_value=True)
@patch("app.domain.services.otp_service.generate_otp", return_value="123456")
def test_confirm_email_valid_sends_otp(mock_gen, mock_send_email, mock_mask, event_loop):
    """A valid email at CONFIRM_EMAIL should generate+send OTP and transition to ENTER_OTP."""
    session = {"state": CHANGE_NUMBER_CONFIRM_EMAIL, "data": {}, "lang": "en"}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_CONFIRM_EMAIL, "subash@gmail.com", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CHANGE_NUMBER_ENTER_OTP
    assert session["data"]["change_number_email"] == "subash@gmail.com"
    mock_gen.assert_called_once_with(WA_ID, "change_number")
    mock_send_email.assert_awaited_once_with("subash@gmail.com", "123456", "en")
    mock_mask.assert_called_once_with("subash@gmail.com")
    kwargs["send"].assert_awaited_once_with(
        WA_ID, "[CHANGE_NUMBER_OTP_SENT]"
    )
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ── 5. CHANGE_NUMBER_CONFIRM_EMAIL — invalid email → stays ──────────


def test_confirm_email_invalid(event_loop):
    """An invalid email (no '@') should stay in CONFIRM_EMAIL and show error."""
    session = {"state": CHANGE_NUMBER_CONFIRM_EMAIL, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_CONFIRM_EMAIL, "not-an-email", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    # State should NOT change
    assert session["state"] == CHANGE_NUMBER_CONFIRM_EMAIL
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_INVALID_EMAIL]")
    kwargs["session_cache"].save_session.assert_not_awaited()


# ── 6. CHANGE_NUMBER_CONFIRM_EMAIL — NotImplementedError fallback ────


@patch(
    "app.domain.services.otp_service.send_otp_email",
    new_callable=AsyncMock,
    side_effect=NotImplementedError("not yet"),
)
@patch("app.domain.services.otp_service.generate_otp", return_value="654321")
def test_confirm_email_not_implemented_fallback(mock_gen, mock_send_email, event_loop):
    """NotImplementedError from send_otp_email should fall back to CA path."""
    session = {"state": CHANGE_NUMBER_CONFIRM_EMAIL, "data": {}, "lang": "en"}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_CONFIRM_EMAIL, "subash@gmail.com", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CHANGE_NUMBER_CA_VERIFY
    # Two messages: EMAIL_NOT_AVAILABLE + CA_UPLOAD
    assert kwargs["send"].await_count == 2
    kwargs["send"].assert_any_await(WA_ID, "[CHANGE_NUMBER_EMAIL_NOT_AVAILABLE]")
    kwargs["send"].assert_any_await(WA_ID, "[CHANGE_NUMBER_CA_UPLOAD]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ── 7. CHANGE_NUMBER_ENTER_OTP — correct OTP → SUCCESS ──────────────


@patch("app.domain.services.otp_service.verify_otp", return_value=True)
@patch("app.domain.services.otp_service.is_locked", return_value=False)
def test_enter_otp_correct(mock_is_locked, mock_verify, event_loop):
    """Correct OTP should transition to CHANGE_NUMBER_SUCCESS."""
    session = {"state": CHANGE_NUMBER_ENTER_OTP, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_ENTER_OTP, "123456", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CHANGE_NUMBER_SUCCESS
    assert session["data"]["number_change_verified"] is True
    mock_is_locked.assert_called_once_with(WA_ID)
    mock_verify.assert_called_once_with(WA_ID, "change_number", "123456")
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_SUCCESS]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ── 8. CHANGE_NUMBER_ENTER_OTP — wrong OTP → stays ──────────────────


@patch("app.domain.services.otp_service.verify_otp", return_value=False)
@patch("app.domain.services.otp_service.is_locked", return_value=False)
def test_enter_otp_wrong(mock_is_locked, mock_verify, event_loop):
    """Wrong OTP should stay in ENTER_OTP and show invalid message."""
    session = {"state": CHANGE_NUMBER_ENTER_OTP, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_ENTER_OTP, "000000", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    # State should NOT change
    assert session["state"] == CHANGE_NUMBER_ENTER_OTP
    mock_verify.assert_called_once_with(WA_ID, "change_number", "000000")
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_INVALID_OTP]")
    kwargs["session_cache"].save_session.assert_not_awaited()


# ── 9. CHANGE_NUMBER_ENTER_OTP — locked → LOCKED ────────────────────


@patch("app.domain.services.otp_service.is_locked", return_value=True)
def test_enter_otp_locked(mock_is_locked, event_loop):
    """Locked user at ENTER_OTP should transition to LOCKED."""
    session = {"state": CHANGE_NUMBER_ENTER_OTP, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_ENTER_OTP, "123456", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == CHANGE_NUMBER_LOCKED
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_LOCKED]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    mock_is_locked.assert_called_once_with(WA_ID)


# ── 10. CHANGE_NUMBER_SUCCESS — any text → SETTINGS_MENU ────────────


def test_success_returns_to_settings(event_loop):
    """Any text at SUCCESS should transition to SETTINGS_MENU."""
    session = {"state": CHANGE_NUMBER_SUCCESS, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_SUCCESS, "anything", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == SETTINGS_MENU
    kwargs["send"].assert_awaited_once_with(WA_ID, "[SETTINGS_MENU]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ── 11. CHANGE_NUMBER_LOCKED — any text → SETTINGS_MENU ─────────────


def test_locked_returns_to_settings(event_loop):
    """Any text at LOCKED should transition to SETTINGS_MENU."""
    session = {"state": CHANGE_NUMBER_LOCKED, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_LOCKED, "anything", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == SETTINGS_MENU
    kwargs["send"].assert_awaited_once_with(WA_ID, "[SETTINGS_MENU]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ── 12. CHANGE_NUMBER_CA_VERIFY — text → re-show upload prompt ──────


def test_ca_verify_reshows_upload_prompt(event_loop):
    """Text at CA_VERIFY should re-send the upload prompt."""
    session = {"state": CHANGE_NUMBER_CA_VERIFY, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_CA_VERIFY, "some text", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    # State should NOT change — still waiting for document upload
    assert session["state"] == CHANGE_NUMBER_CA_VERIFY
    kwargs["send"].assert_awaited_once_with(WA_ID, "[CHANGE_NUMBER_CA_UPLOAD]")
    kwargs["session_cache"].save_session.assert_not_awaited()


# ── 13. CHANGE_NUMBER_CA_PENDING — any text → SETTINGS_MENU ─────────


def test_ca_pending_returns_to_settings(event_loop):
    """Any text at CA_PENDING should transition to SETTINGS_MENU."""
    session = {"state": CHANGE_NUMBER_CA_PENDING, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle(
            CHANGE_NUMBER_CA_PENDING, "anything", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == SETTINGS_MENU
    kwargs["send"].assert_awaited_once_with(WA_ID, "[SETTINGS_MENU]")
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ── 14. Unhandled state returns None ─────────────────────────────────


def test_unhandled_state_returns_none(event_loop):
    """A state not in HANDLED_STATES should return None."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        change_number.handle("MAIN_MENU", "hi", WA_ID, session, **kwargs)
    )

    assert result is None
