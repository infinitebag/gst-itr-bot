# tests/test_gst_onboarding.py
"""Tests for the GST onboarding flow handler (gst_onboarding.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.wa_handlers import gst_onboarding
from app.api.routes.wa_handlers.gst_onboarding import (
    GST_FILING_FREQUENCY,
    GST_GSTIN_CONFIRM,
    GST_MENU,
    GST_MULTI_GST_ADD,
    GST_MULTI_GST_CHECK,
    GST_SEGMENT_DONE,
    GST_START_GSTIN,
    GST_TURNOVER_BAND,
)

# Valid GSTIN that passes regex: 2-digit state + 5 alpha + 4 digit + 1 alpha + 1 alphanumeric + Z + 1 alphanumeric
VALID_GSTIN = "36AABCU9603R1ZM"
VALID_GSTIN_2 = "29AABCU9603R1ZN"
INVALID_GSTIN = "NOTAVALIDGSTIN"
WA_ID = "919999999999"

# Patch targets — these are lazy-imported inside function bodies, so we patch
# at their *definition* module, not at the gst_onboarding module level.
_PATCH_LOOKUP = "app.domain.services.gstin_lookup.lookup_gstin_details"
_PATCH_SEGMENT = "app.domain.services.segment_detection.detect_segment"
_PATCH_GET_DB = "app.core.db.get_db"
_PATCH_BUILD_MENU = "app.domain.services.whatsapp_menu_builder.build_gst_menu"


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


# ── Unhandled state ──────────────────────────────────────────────

def test_unhandled_state_returns_none(event_loop):
    """Handler should return None for states it does not manage."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)
    result = event_loop.run_until_complete(
        gst_onboarding.handle("MAIN_MENU", "hi", WA_ID, session, **kwargs)
    )
    assert result is None


# ── 1. GST_START_GSTIN ───────────────────────────────────────────

@patch(_PATCH_LOOKUP, new_callable=AsyncMock)
def test_start_gstin_valid_triggers_lookup(mock_lookup, event_loop):
    """A valid GSTIN should trigger the lookup and move to GSTIN_CONFIRM."""
    mock_lookup.return_value = {
        "legal_name": "Test Corp",
        "state": "Telangana",
        "status": "Active",
    }

    session = {"state": GST_START_GSTIN, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_START_GSTIN, VALID_GSTIN, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_GSTIN_CONFIRM
    assert session["data"]["gstin"] == VALID_GSTIN
    assert session["data"]["business_name"] == "Test Corp"
    assert session["data"]["gstin_state"] == "Telangana"
    assert session["data"]["gstin_status"] == "Active"
    kwargs["send"].assert_awaited()
    kwargs["session_cache"].save_session.assert_awaited()


def test_start_gstin_invalid_shows_error(event_loop):
    """An invalid GSTIN should return an error message without changing state."""
    session = {"state": GST_START_GSTIN, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_START_GSTIN, INVALID_GSTIN, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should NOT change
    assert session["state"] == GST_START_GSTIN
    # send called with INVALID_GSTIN translation key
    kwargs["send"].assert_awaited_once_with(WA_ID, "[INVALID_GSTIN]")


@patch(_PATCH_LOOKUP, new_callable=AsyncMock, return_value=None)
def test_start_gstin_lookup_fails_skips_confirm(mock_lookup, event_loop):
    """When lookup returns None, skip confirm and go straight to filing frequency."""
    session = {"state": GST_START_GSTIN, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_START_GSTIN, VALID_GSTIN, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # Should skip GSTIN_CONFIRM and go to FILING_FREQUENCY
    assert session["state"] == GST_FILING_FREQUENCY
    assert session["data"]["business_name"] == ""


@patch(_PATCH_LOOKUP, new_callable=AsyncMock, side_effect=Exception("API down"))
def test_start_gstin_lookup_exception_skips_confirm(mock_lookup, event_loop):
    """When lookup raises an exception, skip confirm gracefully."""
    session = {"state": GST_START_GSTIN, "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_START_GSTIN, VALID_GSTIN, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # Should skip GSTIN_CONFIRM and go to FILING_FREQUENCY
    assert session["state"] == GST_FILING_FREQUENCY
    assert session["data"]["business_name"] == ""


# ── 2. GST_GSTIN_CONFIRM ────────────────────────────────────────

def test_gstin_confirm_yes_proceeds(event_loop):
    """Selecting '1' (yes) should proceed to filing frequency."""
    session = {
        "state": GST_GSTIN_CONFIRM,
        "data": {"gstin": VALID_GSTIN, "business_name": "Test Corp"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_GSTIN_CONFIRM, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_FILING_FREQUENCY
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_FREQUENCY]")


def test_gstin_confirm_reenter_goes_back(event_loop):
    """Selecting '2' (re-enter) should go back to GSTIN entry."""
    session = {
        "state": GST_GSTIN_CONFIRM,
        "data": {"gstin": VALID_GSTIN, "business_name": "Test Corp"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_GSTIN_CONFIRM, "2", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_START_GSTIN
    # gstin and business_name should be cleared
    assert "gstin" not in session["data"]
    assert "business_name" not in session["data"]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_ASK_GSTIN]")


def test_gstin_confirm_invalid_choice(event_loop):
    """An invalid choice should re-prompt."""
    session = {
        "state": GST_GSTIN_CONFIRM,
        "data": {"gstin": VALID_GSTIN, "business_name": "Test Corp"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_GSTIN_CONFIRM, "banana", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should stay unchanged
    assert session["state"] == GST_GSTIN_CONFIRM
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_CONFIRM_INVALID]")


# ── 3. GST_FILING_FREQUENCY ─────────────────────────────────────

@pytest.mark.parametrize(
    "choice, expected_mode",
    [("1", "monthly"), ("2", "quarterly"), ("3", "composition")],
)
def test_filing_frequency_valid_choices(event_loop, choice, expected_mode):
    """Valid choices (1/2/3) should set filing_mode and proceed to turnover band."""
    session = {"state": GST_FILING_FREQUENCY, "data": {"gstin": VALID_GSTIN}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_FILING_FREQUENCY, choice, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["filing_mode"] == expected_mode
    assert session["state"] == GST_TURNOVER_BAND
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_TURNOVER]")


def test_filing_frequency_invalid_re_prompts(event_loop):
    """An invalid choice should re-prompt with the frequency menu."""
    session = {"state": GST_FILING_FREQUENCY, "data": {"gstin": VALID_GSTIN}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_FILING_FREQUENCY, "9", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State stays at GST_FILING_FREQUENCY
    assert session["state"] == GST_FILING_FREQUENCY
    assert "filing_mode" not in session["data"]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_FREQUENCY]")


# ── 4. GST_TURNOVER_BAND ────────────────────────────────────────

@pytest.mark.parametrize(
    "choice, expected_band",
    [("1", "below_5cr"), ("2", "5_to_50cr"), ("3", "above_50cr")],
)
def test_turnover_band_valid_choices(event_loop, choice, expected_band):
    """Valid choices should set turnover_band and proceed to multi-GST check."""
    session = {"state": GST_TURNOVER_BAND, "data": {"gstin": VALID_GSTIN}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_TURNOVER_BAND, choice, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["turnover_band"] == expected_band
    assert session["state"] == GST_MULTI_GST_CHECK
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_MULTI_CHECK]")


def test_turnover_band_invalid_re_prompts(event_loop):
    """An invalid choice should re-prompt with the turnover menu."""
    session = {"state": GST_TURNOVER_BAND, "data": {"gstin": VALID_GSTIN}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_TURNOVER_BAND, "7", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_TURNOVER_BAND
    assert "turnover_band" not in session["data"]
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_TURNOVER]")


# ── 5. GST_MULTI_GST_CHECK ──────────────────────────────────────

@patch(_PATCH_SEGMENT, return_value="small")
def test_multi_gst_check_no_finishes_onboarding(mock_seg, event_loop):
    """Choosing '1' (no) should finish onboarding with segment detection."""
    session = {
        "state": GST_MULTI_GST_CHECK,
        "data": {"gstin": VALID_GSTIN, "turnover_band": "below_5cr"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_CHECK, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["multi_gstin"] is False
    assert session["data"]["additional_gstins"] == []
    assert session["data"]["gst_onboarded"] is True
    assert session["data"]["client_segment"] == "small"
    assert session["state"] == GST_SEGMENT_DONE
    mock_seg.assert_called_once_with(annual_turnover=2_00_00_000, gstin_count=1)


@patch(_PATCH_SEGMENT, return_value="medium")
def test_multi_gst_check_no_medium_segment(mock_seg, event_loop):
    """Choosing '1' (no) with medium turnover should detect medium segment."""
    session = {
        "state": GST_MULTI_GST_CHECK,
        "data": {"gstin": VALID_GSTIN, "turnover_band": "5_to_50cr"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_CHECK, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["client_segment"] == "medium"
    mock_seg.assert_called_once_with(annual_turnover=20_00_00_000, gstin_count=1)


def test_multi_gst_check_yes_goes_to_add(event_loop):
    """Choosing '2' (yes) should proceed to add additional GSTINs."""
    session = {
        "state": GST_MULTI_GST_CHECK,
        "data": {"gstin": VALID_GSTIN, "turnover_band": "below_5cr"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_CHECK, "2", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["multi_gstin"] is True
    assert session["state"] == GST_MULTI_GST_ADD
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_MULTI_ADD]")


def test_multi_gst_check_invalid_re_prompts(event_loop):
    """An invalid choice should re-prompt."""
    session = {
        "state": GST_MULTI_GST_CHECK,
        "data": {"gstin": VALID_GSTIN, "turnover_band": "below_5cr"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_CHECK, "banana", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_MULTI_GST_CHECK
    kwargs["send"].assert_awaited_once_with(WA_ID, "[GST_ONBOARD_MULTI_CHECK]")


# ── 5b. GST_MULTI_GST_ADD ───────────────────────────────────────

def test_multi_gst_add_valid_gstin(event_loop):
    """Adding a valid GSTIN should append it to additional_gstins."""
    session = {
        "state": GST_MULTI_GST_ADD,
        "data": {
            "gstin": VALID_GSTIN,
            "multi_gstin": True,
            "additional_gstins": [],
            "turnover_band": "below_5cr",
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_ADD, VALID_GSTIN_2, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert VALID_GSTIN_2 in session["data"]["additional_gstins"]
    assert len(session["data"]["additional_gstins"]) == 1


def test_multi_gst_add_duplicate_gstin_not_added(event_loop):
    """A duplicate GSTIN should not be added again."""
    session = {
        "state": GST_MULTI_GST_ADD,
        "data": {
            "gstin": VALID_GSTIN,
            "multi_gstin": True,
            "additional_gstins": [VALID_GSTIN_2],
            "turnover_band": "below_5cr",
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_ADD, VALID_GSTIN_2, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # Should still have exactly one entry (no duplicate)
    assert session["data"]["additional_gstins"].count(VALID_GSTIN_2) == 1


def test_multi_gst_add_primary_gstin_not_added(event_loop):
    """Adding the primary GSTIN as additional should not duplicate it."""
    session = {
        "state": GST_MULTI_GST_ADD,
        "data": {
            "gstin": VALID_GSTIN,
            "multi_gstin": True,
            "additional_gstins": [],
            "turnover_band": "below_5cr",
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_ADD, VALID_GSTIN, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # Primary GSTIN should NOT be in additional list
    assert VALID_GSTIN not in session["data"]["additional_gstins"]


def test_multi_gst_add_invalid_gstin_shows_error(event_loop):
    """An invalid GSTIN should show an error but keep state."""
    session = {
        "state": GST_MULTI_GST_ADD,
        "data": {
            "gstin": VALID_GSTIN,
            "multi_gstin": True,
            "additional_gstins": [],
            "turnover_band": "below_5cr",
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_ADD, INVALID_GSTIN, WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_MULTI_GST_ADD
    assert len(session["data"]["additional_gstins"]) == 0
    # Should call send twice: once for error, once for re-prompt
    assert kwargs["send"].await_count == 2


@patch(_PATCH_SEGMENT, return_value="medium")
def test_multi_gst_add_done_finishes_onboarding(mock_seg, event_loop):
    """Typing 'done' should finish onboarding and compute segment."""
    session = {
        "state": GST_MULTI_GST_ADD,
        "data": {
            "gstin": VALID_GSTIN,
            "multi_gstin": True,
            "additional_gstins": [VALID_GSTIN_2],
            "turnover_band": "5_to_50cr",
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_ADD, "done", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["gst_onboarded"] is True
    assert session["data"]["client_segment"] == "medium"
    assert session["state"] == GST_SEGMENT_DONE
    # gstin_count should be 2 (primary + 1 additional)
    mock_seg.assert_called_once_with(annual_turnover=20_00_00_000, gstin_count=2)


@patch(_PATCH_SEGMENT, return_value="small")
def test_multi_gst_add_done_case_insensitive(mock_seg, event_loop):
    """'DONE', 'Done', 'done' should all finish onboarding (text is uppercased)."""
    session = {
        "state": GST_MULTI_GST_ADD,
        "data": {
            "gstin": VALID_GSTIN,
            "multi_gstin": True,
            "additional_gstins": [],
            "turnover_band": "below_5cr",
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_MULTI_GST_ADD, "Done", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["gst_onboarded"] is True
    assert session["state"] == GST_SEGMENT_DONE


# ── 6. GST_SEGMENT_DONE ─────────────────────────────────────────

@patch(_PATCH_BUILD_MENU, new_callable=AsyncMock, return_value="Mocked GST Menu")
@patch(_PATCH_GET_DB)
def test_segment_done_open_gst_menu(mock_get_db, mock_build_menu, event_loop):
    """Choosing '1' should open the GST menu."""
    # get_db is an async generator; mock it to yield a single db session
    mock_db = MagicMock()

    async def _fake_get_db():
        yield mock_db

    mock_get_db.side_effect = lambda: _fake_get_db()

    session = {
        "state": GST_SEGMENT_DONE,
        "data": {"gst_onboarded": True, "client_segment": "small"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_SEGMENT_DONE, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_MENU
    kwargs["send_menu_result"].assert_awaited_once_with(WA_ID, "Mocked GST Menu")


@patch(_PATCH_BUILD_MENU, new_callable=AsyncMock, side_effect=Exception("DB error"))
@patch(_PATCH_GET_DB, side_effect=Exception("DB error"))
def test_segment_done_open_gst_menu_fallback(mock_get_db, mock_build_menu, event_loop):
    """Choosing '1' should fall back to GST_SERVICES when build_gst_menu fails."""
    session = {
        "state": GST_SEGMENT_DONE,
        "data": {"gst_onboarded": True, "client_segment": "small"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_SEGMENT_DONE, "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == GST_MENU
    kwargs["send_menu_result"].assert_awaited_once_with(WA_ID, "[GST_SERVICES]")


def test_segment_done_main_menu(event_loop):
    """Choosing '2' should go to the main menu."""
    session = {
        "state": GST_SEGMENT_DONE,
        "data": {"gst_onboarded": True, "client_segment": "medium"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_SEGMENT_DONE, "2", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "MAIN_MENU"
    kwargs["send"].assert_awaited_once_with(WA_ID, "[WELCOME_MENU]")


def test_segment_done_invalid_re_prompts(event_loop):
    """An invalid choice should re-show the segment done screen."""
    session = {
        "state": GST_SEGMENT_DONE,
        "data": {"gst_onboarded": True, "client_segment": "enterprise"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_onboarding.handle(GST_SEGMENT_DONE, "banana", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should remain GST_SEGMENT_DONE
    assert session["state"] == GST_SEGMENT_DONE
    kwargs["send"].assert_awaited_once()


# ── Segment display label ────────────────────────────────────────

def test_segment_display_label_english():
    """Segment label should map correctly for English."""
    from app.api.routes.wa_handlers.gst_onboarding import _segment_display_label

    assert _segment_display_label("small", {"lang": "en"}) == "Small"
    assert _segment_display_label("medium", {"lang": "en"}) == "Medium"
    assert _segment_display_label("enterprise", {"lang": "en"}) == "Large"


def test_segment_display_label_hindi():
    """Segment label should map correctly for Hindi."""
    from app.api.routes.wa_handlers.gst_onboarding import _segment_display_label

    assert _segment_display_label("enterprise", {"lang": "hi"}) == "\u092c\u0921\u093c\u093e"


def test_segment_display_label_unknown_lang_falls_back_to_english():
    """Unknown language should fall back to English labels."""
    from app.api.routes.wa_handlers.gst_onboarding import _segment_display_label

    assert _segment_display_label("small", {"lang": "fr"}) == "Small"


def test_segment_display_label_unknown_segment_returns_raw():
    """Unknown segment code should return the raw string."""
    from app.api.routes.wa_handlers.gst_onboarding import _segment_display_label

    assert _segment_display_label("micro", {"lang": "en"}) == "micro"
