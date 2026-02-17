# tests/test_gst_filing_flow.py
"""Tests for the GST filing sub-flow handler (gst_filing.py).

Covers all states: GST_FILE_SELECT_PERIOD, GST_FILE_CHECKLIST,
GST_NIL_SUGGEST, GST_SUMMARY, GST_FILED_STATUS, and unhandled states.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.wa_handlers import gst_filing


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _make_handler_kwargs(session):
    """Build the kwargs dict expected by gst_filing.handle()."""
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


async def _fake_db_gen():
    """Fake async generator that yields a MagicMock DB session."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.commit = AsyncMock()
    yield db


# ---------------------------------------------------------------------------
# 1) GST_FILE_SELECT_PERIOD -- empty text shows period menu
# ---------------------------------------------------------------------------

def test_select_period_empty_text_shows_menu(event_loop):
    """Empty text in GST_FILE_SELECT_PERIOD should display the period menu."""
    session = {"state": "GST_FILE_SELECT_PERIOD", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILE_SELECT_PERIOD", "", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    kwargs["send"].assert_awaited_once()
    msg = kwargs["send"].call_args[0][1]
    assert "Select a filing period" in msg
    assert "1)" in msg
    assert "BACK" in msg


# ---------------------------------------------------------------------------
# 2) GST_FILE_SELECT_PERIOD -- valid choice "1" selects period -> checklist
# ---------------------------------------------------------------------------

def test_select_period_choice_1_goes_to_checklist(event_loop):
    """Choosing '1' should select the first period and transition to checklist."""
    session = {"state": "GST_FILE_SELECT_PERIOD", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILE_SELECT_PERIOD", "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_FILE_CHECKLIST"
    assert session["data"].get("gst_filing_period") is not None
    # The send should have been called at least once (Selected period + checklist)
    assert kwargs["send"].await_count >= 1
    # State stack should contain the pushed state
    assert "GST_FILE_CHECKLIST" in session.get("_state_stack", [])


# ---------------------------------------------------------------------------
# 3) GST_FILE_SELECT_PERIOD -- "4" triggers custom period entry mode
# ---------------------------------------------------------------------------

def test_select_period_choice_4_custom_entry(event_loop):
    """Choosing '4' should enable custom period input mode."""
    session = {"state": "GST_FILE_SELECT_PERIOD", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILE_SELECT_PERIOD", "4", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["_awaiting_custom_period"] is True
    kwargs["session_cache"].save_session.assert_awaited()
    msg = kwargs["send"].call_args[0][1]
    assert "YYYY-MM" in msg


# ---------------------------------------------------------------------------
# 4) GST_FILE_SELECT_PERIOD -- custom period YYYY-MM accepted
# ---------------------------------------------------------------------------

def test_select_period_custom_yyyy_mm_accepted(event_loop):
    """A valid YYYY-MM input in custom-period mode should be accepted."""
    session = {
        "state": "GST_FILE_SELECT_PERIOD",
        "data": {"_awaiting_custom_period": True},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILE_SELECT_PERIOD", "2025-03", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["gst_filing_period"] == "2025-03"
    # Custom-period flag should be cleared
    assert "_awaiting_custom_period" not in session["data"]
    assert session["state"] == "GST_FILE_CHECKLIST"
    # The selected-period message should mention March 2025
    first_send_msg = kwargs["send"].call_args_list[0][0][1]
    assert "March 2025" in first_send_msg


# ---------------------------------------------------------------------------
# 5) GST_FILE_CHECKLIST -- "1" with data -> goes to GST_SUMMARY
# ---------------------------------------------------------------------------

def test_checklist_option_1_with_data_goes_to_summary(event_loop):
    """Option 1 on checklist with invoice data should go to GST_SUMMARY."""
    session = {
        "state": "GST_FILE_CHECKLIST",
        "data": {
            "gst_filing_period": "2025-03",
            "invoices_outward_count": 5,
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILE_CHECKLIST", "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_SUMMARY"
    assert "GST_SUMMARY" in session.get("_state_stack", [])
    # Should show the summary screen
    msg = kwargs["send"].call_args[0][1]
    assert "Filing Summary" in msg


# ---------------------------------------------------------------------------
# 6) GST_FILE_CHECKLIST -- "1" without data -> goes to GST_NIL_SUGGEST
# ---------------------------------------------------------------------------

def test_checklist_option_1_no_data_goes_to_nil_suggest(event_loop):
    """Option 1 on checklist with no invoice data should go to GST_NIL_SUGGEST."""
    session = {
        "state": "GST_FILE_CHECKLIST",
        "data": {"gst_filing_period": "2025-03"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILE_CHECKLIST", "1", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_NIL_SUGGEST"
    msg = kwargs["send"].call_args[0][1]
    assert "NIL" in msg


# ---------------------------------------------------------------------------
# 7) GST_FILE_CHECKLIST -- "3" -> pops state back
# ---------------------------------------------------------------------------

def test_checklist_option_3_pops_state(event_loop):
    """Option 3 on checklist should pop state and go back."""
    session = {
        "state": "GST_FILE_CHECKLIST",
        "data": {"gst_filing_period": "2025-03"},
        "_state_stack": ["GST_FILE_SELECT_PERIOD"],
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILE_CHECKLIST", "3", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    # State should be popped to previous
    assert session["state"] == "GST_FILE_SELECT_PERIOD"
    kwargs["session_cache"].save_session.assert_awaited()


# ---------------------------------------------------------------------------
# 8) GST_NIL_SUGGEST -- "1" -> files NIL return, goes back
# ---------------------------------------------------------------------------

def test_nil_suggest_option_1_files_nil_return(event_loop):
    """Option 1 on NIL suggest should file a NIL return and pop state."""
    session = {
        "state": "GST_NIL_SUGGEST",
        "data": {"gst_filing_period": "2025-03", "gstin": "29ABCDE1234F1Z5"},
        "_state_stack": ["GST_FILE_CHECKLIST"],
    }
    kwargs = _make_handler_kwargs(session)

    mock_result = {"success": True, "arn": "ARN123456"}
    with patch(
        "app.domain.services.gst_service.file_nil_return_mastergst",
        new=AsyncMock(return_value=mock_result),
    ):
        result = event_loop.run_until_complete(
            gst_filing.handle("GST_NIL_SUGGEST", "1", WA_ID, session, **kwargs)
        )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_FILE_CHECKLIST"
    # Period should be cleared after filing
    assert "gst_filing_period" not in session["data"]
    msg = kwargs["send"].call_args[0][1]
    assert "NIL return filed" in msg


# ---------------------------------------------------------------------------
# 9) GST_NIL_SUGGEST -- "3" -> back to checklist
# ---------------------------------------------------------------------------

def test_nil_suggest_option_3_back_to_checklist(event_loop):
    """Option 3 on NIL suggest should go back to the checklist screen."""
    session = {
        "state": "GST_NIL_SUGGEST",
        "data": {"gst_filing_period": "2025-03"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_NIL_SUGGEST", "3", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_FILE_CHECKLIST"
    # Should re-display the checklist
    msg = kwargs["send"].call_args[0][1]
    assert "Filing Checklist" in msg


# ---------------------------------------------------------------------------
# 10) GST_SUMMARY -- "1" -> sends to CA (stub)
# ---------------------------------------------------------------------------

def test_summary_option_1_send_to_ca(event_loop):
    """Option 1 on summary should send to CA and pop state."""
    session = {
        "state": "GST_SUMMARY",
        "data": {
            "gst_filing_period": "2025-03",
            "invoices_outward_count": 5,
            "output_tax_total": 1800,
        },
        "_state_stack": ["GST_FILE_CHECKLIST"],
    }
    kwargs = _make_handler_kwargs(session)

    # Mock the service imports that happen inside the handler
    with patch(
        "app.domain.services.gst_workflow.create_gst_draft_from_session",
        new=AsyncMock(return_value=MagicMock()),
    ), patch("app.core.db.get_db", return_value=_fake_db_gen()):
        result = event_loop.run_until_complete(
            gst_filing.handle("GST_SUMMARY", "1", WA_ID, session, **kwargs)
        )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_FILE_CHECKLIST"
    # Period should be cleared
    assert "gst_filing_period" not in session["data"]
    msg = kwargs["send"].call_args[0][1]
    assert "sent to your CA" in msg or "queued for CA review" in msg


# ---------------------------------------------------------------------------
# 11) GST_SUMMARY -- "2" -> files now (stub)
# ---------------------------------------------------------------------------

def test_summary_option_2_file_now(event_loop):
    """Option 2 on summary should initiate filing and pop state."""
    session = {
        "state": "GST_SUMMARY",
        "data": {
            "gst_filing_period": "2025-03",
            "invoices_outward_count": 5,
            "output_tax_total": 1800,
            "gstin": "29ABCDE1234F1Z5",
        },
        "_state_stack": ["GST_FILE_CHECKLIST"],
    }
    kwargs = _make_handler_kwargs(session)

    # Mock the service imports that happen inside the handler
    with patch(
        "app.domain.services.gst_service.file_gstr3b_from_session",
        new=AsyncMock(return_value=MagicMock()),
    ):
        result = event_loop.run_until_complete(
            gst_filing.handle("GST_SUMMARY", "2", WA_ID, session, **kwargs)
        )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_FILE_CHECKLIST"
    assert "gst_filing_period" not in session["data"]
    msg = kwargs["send"].call_args[0][1]
    assert "Filing" in msg or "filing" in msg


# ---------------------------------------------------------------------------
# 12) GST_SUMMARY -- "3" -> back to checklist
# ---------------------------------------------------------------------------

def test_summary_option_3_back_to_checklist(event_loop):
    """Option 3 on summary should go back to checklist screen."""
    session = {
        "state": "GST_SUMMARY",
        "data": {
            "gst_filing_period": "2025-03",
            "invoices_outward_count": 5,
            "output_tax_total": 1800,
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_SUMMARY", "3", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_FILE_CHECKLIST"
    msg = kwargs["send"].call_args[0][1]
    assert "Filing Checklist" in msg


# ---------------------------------------------------------------------------
# 13) GST_FILED_STATUS -- shows status then pops state
# ---------------------------------------------------------------------------

@patch("app.domain.services.gst_service.get_current_gst_period", return_value="2025-03")
def test_filed_status_shows_status_and_pops(mock_period, event_loop):
    """GST_FILED_STATUS should show status and pop back to previous state."""
    session = {
        "state": "GST_FILED_STATUS",
        "data": {
            "gstin": "36AABCU9603R1ZM",
            "last_filing": {
                "status": "Filed",
                "period": "2025-02",
                "arn": "AA123456789",
            },
        },
        "_state_stack": ["GST_MENU"],
    }
    kwargs = _make_handler_kwargs(session)

    with patch("app.core.db.get_db", return_value=_fake_db_gen()):
        result = event_loop.run_until_complete(
            gst_filing.handle("GST_FILED_STATUS", "", WA_ID, session, **kwargs)
        )

    assert result is not None
    assert result.status_code == 200
    # State should have been popped back to GST_MENU
    assert session["state"] == "GST_MENU"
    msg = kwargs["send"].call_args[0][1]
    assert "36AABCU9603R1ZM" in msg
    assert "Filed" in msg
    assert "AA123456789" in msg
    mock_period.assert_called_once()


@patch("app.domain.services.gst_service.get_current_gst_period", return_value="2025-03")
def test_filed_status_no_recent_filing(mock_period, event_loop):
    """GST_FILED_STATUS with no filing record should show 'no recent filings'."""
    session = {
        "state": "GST_FILED_STATUS",
        "data": {"gstin": "36AABCU9603R1ZM"},
        "_state_stack": ["GST_MENU"],
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("GST_FILED_STATUS", "", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_MENU"
    msg = kwargs["send"].call_args[0][1]
    assert "No recent filings" in msg
    assert "36AABCU9603R1ZM" in msg
    mock_period.assert_called_once()


# ---------------------------------------------------------------------------
# 14) Unhandled state returns None
# ---------------------------------------------------------------------------

def test_unhandled_state_returns_none(event_loop):
    """An unhandled state should make handle() return None."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_filing.handle("MAIN_MENU", "hi", WA_ID, session, **kwargs)
    )

    assert result is None
    kwargs["send"].assert_not_awaited()
