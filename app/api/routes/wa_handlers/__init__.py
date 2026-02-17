# app/api/routes/wa_handlers/__init__.py
"""
Modularized WhatsApp state handlers.

Each sub-module exposes an ``async def handle(...)`` coroutine.
The main ``whatsapp.py`` webhook dispatches to these handlers based on
the current session state.

Handler signature::

    async def handle(
        state: str,
        text: str,
        wa_id: str,
        session: dict,
        *,
        session_cache,
        send,
        send_buttons,
        send_menu_result,
        t,
        push_state,
        pop_state,
        state_to_screen_key,
        get_lang,
    ) -> Response | None

If the handler recognises the state it returns a ``Response``; otherwise
it returns ``None`` so the next handler in the chain can try.
"""

from __future__ import annotations

from . import (
    gst_onboarding,
    gst_upload,
    gst_filing,
    gst_tax_payment,
    gst_compliance,
    einvoice,
    ewaybill,
    gst_wizard,
    gst_credit_check,
    multi_gstin,
    refund_notice,
    notification_settings,
    connect_ca,
    settings_handler,
    change_number,
    itr_filing_flow,
    itr_doc_upload,
    session_expiry,
    module_switch,
)

# Ordered list of handlers — the main webhook tries each in sequence.
# session_expiry and module_switch first (session-level concerns),
# then gst_onboarding and feature handlers.
HANDLER_CHAIN = [
    session_expiry,
    module_switch,
    gst_onboarding,
    gst_upload,
    gst_filing,
    gst_tax_payment,
    gst_compliance,
    einvoice,
    ewaybill,
    gst_wizard,
    gst_credit_check,
    multi_gstin,
    refund_notice,
    notification_settings,
    connect_ca,
    settings_handler,
    change_number,
    itr_filing_flow,
    itr_doc_upload,
]

__all__ = [
    "HANDLER_CHAIN",
    "session_expiry",
    "module_switch",
    "gst_onboarding",
    "gst_upload",
    "gst_filing",
    "gst_tax_payment",
    "gst_compliance",
    "einvoice",
    "ewaybill",
    "gst_wizard",
    "gst_credit_check",
    "multi_gstin",
    "refund_notice",
    "notification_settings",
    "connect_ca",
    "settings_handler",
    "change_number",
    "itr_filing_flow",
    "itr_doc_upload",
]
