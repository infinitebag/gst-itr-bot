# tests/test_wa_handlers.py
"""Tests for modular WhatsApp handler chain (wa_handlers/)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.wa_handlers import HANDLER_CHAIN


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


def test_handler_chain_has_modules():
    """Handler chain should contain all registered handler modules."""
    assert len(HANDLER_CHAIN) == 19
    module_names = [m.__name__.split(".")[-1] for m in HANDLER_CHAIN]
    assert "session_expiry" in module_names
    assert "module_switch" in module_names
    assert "gst_onboarding" in module_names
    assert "gst_upload" in module_names
    assert "gst_filing" in module_names
    assert "gst_tax_payment" in module_names
    assert "gst_compliance" in module_names
    assert "einvoice" in module_names
    assert "ewaybill" in module_names
    assert "gst_wizard" in module_names
    assert "gst_credit_check" in module_names
    assert "multi_gstin" in module_names
    assert "refund_notice" in module_names
    assert "notification_settings" in module_names
    assert "connect_ca" in module_names
    assert "settings_handler" in module_names
    assert "change_number" in module_names
    assert "itr_filing_flow" in module_names
    assert "itr_doc_upload" in module_names


def test_handler_chain_unhandled_state_returns_none(event_loop):
    """Handlers should return None for states they don't handle."""
    session = {"state": "MAIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    for handler_mod in HANDLER_CHAIN:
        result = event_loop.run_until_complete(
            handler_mod.handle("MAIN_MENU", "hi", "919999999999", session, **kwargs)
        )
        assert result is None, f"{handler_mod.__name__} should return None for MAIN_MENU"


def test_einvoice_handler_handles_menu(event_loop):
    """e-Invoice handler should handle EINVOICE_MENU state."""
    from app.api.routes.wa_handlers import einvoice

    session = {"state": "EINVOICE_MENU", "data": {"gstin": "36AABCU9603R1ZM"}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        einvoice.handle("EINVOICE_MENU", "1", "919999999999", session, **kwargs)
    )
    assert result is not None
    assert result.status_code == 200
    # Should transition to EINVOICE_UPLOAD
    assert session["state"] == "EINVOICE_UPLOAD"


def test_ewaybill_handler_handles_menu(event_loop):
    """e-WayBill handler should handle EWAYBILL_MENU state."""
    from app.api.routes.wa_handlers import ewaybill

    session = {"state": "EWAYBILL_MENU", "data": {"gstin": "36AABCU9603R1ZM"}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        ewaybill.handle("EWAYBILL_MENU", "1", "919999999999", session, **kwargs)
    )
    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "EWAYBILL_UPLOAD"


def test_wizard_handler_handles_sales_done(event_loop):
    """Wizard handler should handle SMALL_WIZARD_SALES when done."""
    from app.api.routes.wa_handlers import gst_wizard

    session = {
        "state": "SMALL_WIZARD_SALES",
        "data": {
            "wizard_sales_invoices": [
                {"total_amount": 10000, "igst_amount": 1800, "cgst_amount": 0, "sgst_amount": 0}
            ],
        },
    }
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        gst_wizard.handle("SMALL_WIZARD_SALES", "done", "919999999999", session, **kwargs)
    )
    assert result is not None
    assert result.status_code == 200
    # Should transition to purchases phase
    assert session["state"] == "SMALL_WIZARD_PURCHASES"


def test_multi_gstin_handler_handles_add(event_loop):
    """Multi-GSTIN handler should transition to ADD state."""
    from app.api.routes.wa_handlers import multi_gstin

    session = {"state": "MULTI_GSTIN_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        multi_gstin.handle("MULTI_GSTIN_MENU", "1", "919999999999", session, **kwargs)
    )
    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "MULTI_GSTIN_ADD"


def test_notification_handler_saves_prefs(event_loop):
    """Notification handler should save preferences."""
    from app.api.routes.wa_handlers import notification_settings

    session = {"state": "NOTIFICATION_SETTINGS", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        notification_settings.handle(
            "NOTIFICATION_SETTINGS", "4", "919999999999", session, **kwargs
        )
    )
    assert result is not None
    assert result.status_code == 200
    prefs = session["data"]["notification_prefs"]
    assert prefs["filing_reminders"] is True
    assert prefs["risk_alerts"] is True
    assert prefs["status_updates"] is True


def test_refund_handler_handles_menu(event_loop):
    """Refund handler should handle REFUND_MENU state."""
    from app.api.routes.wa_handlers import refund_notice

    session = {"state": "REFUND_MENU", "data": {}}
    kwargs = _make_handler_kwargs(session)

    result = event_loop.run_until_complete(
        refund_notice.handle("REFUND_MENU", "1", "919999999999", session, **kwargs)
    )
    assert result is not None
    assert result.status_code == 200
    assert session["state"] == "REFUND_TYPE"


def test_all_handled_states_covered():
    """Every handler's HANDLED_STATES should be non-empty."""
    for handler_mod in HANDLER_CHAIN:
        assert hasattr(handler_mod, "HANDLED_STATES")
        assert len(handler_mod.HANDLED_STATES) > 0, f"{handler_mod.__name__} has empty HANDLED_STATES"


def test_no_duplicate_states_across_handlers():
    """No state should be claimed by more than one handler."""
    all_states = []
    for handler_mod in HANDLER_CHAIN:
        for s in handler_mod.HANDLED_STATES:
            assert s not in all_states, f"State {s} handled by multiple modules"
            all_states.append(s)
