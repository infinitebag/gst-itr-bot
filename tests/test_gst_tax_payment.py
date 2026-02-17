# tests/test_gst_tax_payment.py
"""Tests for the GST tax payment sub-flow handler."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.wa_handlers import gst_tax_payment


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


# ---------------------------------------------------------------------------
# 1. GST_TAX_PAYABLE — shows liability breakdown
# ---------------------------------------------------------------------------
def test_tax_payable_shows_liability_breakdown(event_loop):
    """GST_TAX_PAYABLE should send a liability message and return 200."""
    session = {
        "state": "GST_TAX_PAYABLE",
        "data": {
            "liability_igst": 5000,
            "liability_cgst": 2500,
            "liability_sgst": 2500,
            "liability_late_fee": 100,
            "liability_interest": 50,
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle("GST_TAX_PAYABLE", "anything", WA_ID, session, **kwargs)
    )

    assert result is not None
    assert result.status_code == 200
    kwargs["send"].assert_awaited_once()
    sent_text = kwargs["send"].call_args[0][1]
    # Should contain IGST, CGST, SGST values
    assert "IGST" in sent_text
    assert "CGST" in sent_text
    assert "SGST" in sent_text
    assert "5,000.00" in sent_text
    assert "2,500.00" in sent_text
    # Should include late fee and interest since they are non-zero
    assert "Late fee" in sent_text
    assert "Interest" in sent_text


# ---------------------------------------------------------------------------
# 2. GST_PAYMENT_CAPTURE — step "challan_number" — valid input stores and
#    transitions to date step
# ---------------------------------------------------------------------------
def test_payment_capture_challan_number_valid(event_loop):
    """Valid challan number should be stored and advance to challan_date step."""
    session = {
        "state": "GST_PAYMENT_CAPTURE",
        "data": {"payment_step": "challan_number"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CAPTURE", "CHL-12345", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["payment"]["challan_number"] == "CHL-12345"
    assert session["data"]["payment_step"] == "challan_date"
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    sent_text = kwargs["send"].call_args[0][1]
    assert "DD/MM/YYYY" in sent_text


# ---------------------------------------------------------------------------
# 3. GST_PAYMENT_CAPTURE — step "challan_number" — empty input shows error
# ---------------------------------------------------------------------------
def test_payment_capture_challan_number_empty(event_loop):
    """Empty challan number should show an error and stay on the same step."""
    session = {
        "state": "GST_PAYMENT_CAPTURE",
        "data": {"payment_step": "challan_number"},
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CAPTURE", "   ", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    sent_text = kwargs["send"].call_args[0][1]
    assert "valid challan number" in sent_text.lower()
    # Step should not advance
    assert session["data"]["payment_step"] == "challan_number"
    # Session should NOT be saved on validation error
    kwargs["session_cache"].save_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# 4. GST_PAYMENT_CAPTURE — step "challan_date" — valid DD/MM/YYYY accepted
# ---------------------------------------------------------------------------
def test_payment_capture_challan_date_valid(event_loop):
    """Valid DD/MM/YYYY date should be stored and advance to challan_amount."""
    session = {
        "state": "GST_PAYMENT_CAPTURE",
        "data": {
            "payment_step": "challan_date",
            "payment": {"challan_number": "CHL-12345"},
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CAPTURE", "15/01/2025", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["payment"]["challan_date"] == "15/01/2025"
    assert session["data"]["payment_step"] == "challan_amount"
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ---------------------------------------------------------------------------
# 5. GST_PAYMENT_CAPTURE — step "challan_date" — invalid format shows error
# ---------------------------------------------------------------------------
def test_payment_capture_challan_date_invalid(event_loop):
    """Invalid date format should show an error and stay on challan_date step."""
    session = {
        "state": "GST_PAYMENT_CAPTURE",
        "data": {
            "payment_step": "challan_date",
            "payment": {"challan_number": "CHL-12345"},
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CAPTURE", "2025-01-15", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    sent_text = kwargs["send"].call_args[0][1]
    assert "DD/MM/YYYY" in sent_text
    # Step should not advance
    assert session["data"]["payment_step"] == "challan_date"
    kwargs["session_cache"].save_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# 6. GST_PAYMENT_CAPTURE — step "challan_amount" — valid amount accepted,
#    transitions to GST_PAYMENT_CONFIRM
# ---------------------------------------------------------------------------
def test_payment_capture_challan_amount_valid(event_loop):
    """Valid positive amount should be stored and transition to CONFIRM state."""
    session = {
        "state": "GST_PAYMENT_CAPTURE",
        "data": {
            "payment_step": "challan_amount",
            "payment": {"challan_number": "CHL-12345", "challan_date": "15/01/2025"},
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CAPTURE", "15,000", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["data"]["payment"]["challan_amount"] == "15,000.00"
    assert session["state"] == "GST_PAYMENT_CONFIRM"
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    # Should show payment summary
    sent_text = kwargs["send"].call_args[0][1]
    assert "CHL-12345" in sent_text
    assert "15/01/2025" in sent_text
    assert "15,000.00" in sent_text


# ---------------------------------------------------------------------------
# 7. GST_PAYMENT_CAPTURE — step "challan_amount" — invalid amount shows error
# ---------------------------------------------------------------------------
def test_payment_capture_challan_amount_invalid(event_loop):
    """Non-numeric or non-positive amount should show an error."""
    session = {
        "state": "GST_PAYMENT_CAPTURE",
        "data": {
            "payment_step": "challan_amount",
            "payment": {"challan_number": "CHL-12345", "challan_date": "15/01/2025"},
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CAPTURE", "abc", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    sent_text = kwargs["send"].call_args[0][1]
    assert "valid positive amount" in sent_text.lower()
    # Step should not advance
    assert session["data"]["payment_step"] == "challan_amount"
    kwargs["session_cache"].save_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# 8. GST_PAYMENT_CONFIRM — "1" confirms payment and returns to GST_MENU
# ---------------------------------------------------------------------------
def test_payment_confirm_option_1_confirms(event_loop):
    """Option '1' should confirm payment, clean up data, and go to GST_MENU."""
    session = {
        "state": "GST_PAYMENT_CONFIRM",
        "data": {
            "payment_step": "challan_amount",
            "payment": {
                "challan_number": "CHL-12345",
                "challan_date": "15/01/2025",
                "challan_amount": "15,000.00",
            },
        },
        "_state_stack": ["GST_MENU", "GST_PAYMENT_CONFIRM"],
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CONFIRM", "1", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_MENU"
    # Payment data should be cleaned up
    assert "payment" not in session["data"]
    assert "payment_step" not in session["data"]
    # send called twice: success message + GST menu
    assert kwargs["send"].await_count == 2
    success_msg = kwargs["send"].call_args_list[0][0][1]
    assert "recorded successfully" in success_msg.lower()
    assert "CHL-12345" in success_msg
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)


# ---------------------------------------------------------------------------
# 9. GST_PAYMENT_CONFIRM — "2" re-enters, goes back to capture
# ---------------------------------------------------------------------------
def test_payment_confirm_option_2_re_enters(event_loop):
    """Option '2' should reset payment and go back to GST_PAYMENT_CAPTURE."""
    session = {
        "state": "GST_PAYMENT_CONFIRM",
        "data": {
            "payment_step": "challan_amount",
            "payment": {
                "challan_number": "CHL-12345",
                "challan_date": "15/01/2025",
                "challan_amount": "15,000.00",
            },
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CONFIRM", "2", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "GST_PAYMENT_CAPTURE"
    # Payment data should be reset
    assert "payment" not in session["data"]
    assert session["data"]["payment_step"] == "challan_number"
    kwargs["session_cache"].save_session.assert_awaited_once_with(WA_ID, session)
    sent_text = kwargs["send"].call_args[0][1]
    assert "challan number" in sent_text.lower()


# ---------------------------------------------------------------------------
# 10. GST_PAYMENT_CONFIRM — invalid input re-shows summary
# ---------------------------------------------------------------------------
def test_payment_confirm_invalid_input_reshows_summary(event_loop):
    """Unrecognised input should re-show the payment summary."""
    session = {
        "state": "GST_PAYMENT_CONFIRM",
        "data": {
            "payment": {
                "challan_number": "CHL-12345",
                "challan_date": "15/01/2025",
                "challan_amount": "15,000.00",
            },
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle(
            "GST_PAYMENT_CONFIRM", "hello", WA_ID, session, **kwargs
        )
    )

    assert result is not None
    assert result.status_code == 200
    sent_text = kwargs["send"].call_args[0][1]
    assert "Payment Summary" in sent_text
    assert "CHL-12345" in sent_text
    assert "15/01/2025" in sent_text
    assert "15,000.00" in sent_text
    # Session should NOT be saved for invalid input
    kwargs["session_cache"].save_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# 11. Unhandled state returns None
# ---------------------------------------------------------------------------
def test_unhandled_state_returns_none(event_loop):
    """States not in HANDLED_STATES should cause handle() to return None."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_tax_payment.handle("MAIN_MENU", "hi", WA_ID, session, **kwargs)
    )

    assert result is None
    kwargs["send"].assert_not_awaited()
    kwargs["session_cache"].save_session.assert_not_awaited()
