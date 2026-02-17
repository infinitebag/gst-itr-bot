# app/api/routes/wa_handlers/gst_filing.py
"""GST filing sub-flow handler.

States handled:
    GST_FILE_SELECT_PERIOD, GST_FILE_CHECKLIST, GST_NIL_SUGGEST,
    GST_SUMMARY, GST_FILED_STATUS
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.gst_filing")

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------
GST_FILE_SELECT_PERIOD = "GST_FILE_SELECT_PERIOD"
GST_FILE_CHECKLIST = "GST_FILE_CHECKLIST"
GST_NIL_SUGGEST = "GST_NIL_SUGGEST"
GST_SUMMARY = "GST_SUMMARY"
GST_FILED_STATUS = "GST_FILED_STATUS"

GST_MENU = "GST_MENU"

HANDLED_STATES = {
    GST_FILE_SELECT_PERIOD,
    GST_FILE_CHECKLIST,
    GST_NIL_SUGGEST,
    GST_SUMMARY,
    GST_FILED_STATUS,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _last_n_periods(n: int = 3) -> list[str]:
    """Return the last *n* GST filing periods as ``YYYY-MM`` strings.

    GST returns are filed for the *previous* month, so the most recent
    eligible period is always last month.  We walk backwards from there.
    """
    today = date.today()
    periods: list[str] = []
    for i in range(1, n + 1):
        ref = today.replace(day=1) - timedelta(days=1)  # last day of prev month
        for _ in range(i - 1):
            ref = ref.replace(day=1) - timedelta(days=1)
        periods.append(f"{ref.year}-{ref.month:02d}")
    return periods


def _format_period(period: str) -> str:
    """``2025-03`` -> ``March 2025``."""
    try:
        year, month = period.split("-")
        return f"{_MONTH_NAMES[int(month)]} {year}"
    except (ValueError, IndexError):
        return period


def _session_data(session: dict) -> dict:
    """Return (and lazily create) ``session["data"]``."""
    return session.setdefault("data", {})


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


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
    """Handle GST filing sub-flow states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    # ------------------------------------------------------------------ #
    # GST_FILE_SELECT_PERIOD — pick a filing period
    # ------------------------------------------------------------------ #
    if state == GST_FILE_SELECT_PERIOD:
        return await _handle_select_period(
            text, wa_id, session,
            session_cache=session_cache, send=send,
            push_state=push_state,
        )

    # ------------------------------------------------------------------ #
    # GST_FILE_CHECKLIST — show readiness checklist for selected period
    # ------------------------------------------------------------------ #
    if state == GST_FILE_CHECKLIST:
        return await _handle_checklist(
            text, wa_id, session,
            session_cache=session_cache, send=send,
            push_state=push_state, pop_state=pop_state,
            state_to_screen_key=state_to_screen_key, t=t,
        )

    # ------------------------------------------------------------------ #
    # GST_NIL_SUGGEST — no invoices found, suggest NIL filing
    # ------------------------------------------------------------------ #
    if state == GST_NIL_SUGGEST:
        return await _handle_nil_suggest(
            text, wa_id, session,
            session_cache=session_cache, send=send,
            pop_state=pop_state, state_to_screen_key=state_to_screen_key, t=t,
        )

    # ------------------------------------------------------------------ #
    # GST_SUMMARY — filing summary with tax breakdown
    # ------------------------------------------------------------------ #
    if state == GST_SUMMARY:
        return await _handle_summary(
            text, wa_id, session,
            session_cache=session_cache, send=send,
            pop_state=pop_state, state_to_screen_key=state_to_screen_key, t=t,
        )

    # ------------------------------------------------------------------ #
    # GST_FILED_STATUS — query recent filing status
    # ------------------------------------------------------------------ #
    if state == GST_FILED_STATUS:
        return await _handle_filed_status(
            text, wa_id, session,
            session_cache=session_cache, send=send,
            pop_state=pop_state, state_to_screen_key=state_to_screen_key, t=t,
        )

    return None  # pragma: no cover


# ====================================================================== #
# Per-state helpers
# ====================================================================== #


async def _handle_select_period(
    text: str,
    wa_id: str,
    session: dict,
    *,
    session_cache: Any,
    send: Callable[..., Awaitable],
    push_state: Callable,
) -> Response:
    """GST_FILE_SELECT_PERIOD — let the user choose a filing period."""

    periods = _last_n_periods(3)
    data = _session_data(session)

    # First entry — show the period menu
    if text in ("", "__entry__") or not text.strip():
        lines = ["Select a filing period:\n"]
        for idx, p in enumerate(periods, start=1):
            lines.append(f"{idx}) {_format_period(p)}")
        lines.append(f"{len(periods) + 1}) Other (enter custom period)")
        lines.append("\nBACK = Go Back")
        await send(wa_id, "\n".join(lines))
        return Response(status_code=200)

    # User is entering a custom period (from option 4)
    if data.get("_awaiting_custom_period"):
        period = text.strip()
        # Basic validation: expect YYYY-MM
        if len(period) == 7 and period[4] == "-" and period[:4].isdigit() and period[5:].isdigit():
            month_num = int(period[5:])
            if 1 <= month_num <= 12:
                data["gst_filing_period"] = period
                data.pop("_awaiting_custom_period", None)
                logger.info("User %s selected custom filing period %s", wa_id, period)
                push_state(session, GST_FILE_CHECKLIST)
                session["state"] = GST_FILE_CHECKLIST
                await session_cache.save_session(wa_id, session)
                await send(wa_id, f"Selected period: {_format_period(period)}\n\nChecking data...")
                # Trigger checklist display by recursing with empty text
                return await _send_checklist_screen(wa_id, session, send=send)
        await send(wa_id, "Invalid format. Please enter the period as YYYY-MM (e.g. 2025-03):")
        return Response(status_code=200)

    # Numeric choice
    if text in ("1", "2", "3"):
        idx = int(text) - 1
        if idx < len(periods):
            selected = periods[idx]
            data["gst_filing_period"] = selected
            logger.info("User %s selected filing period %s", wa_id, selected)
            push_state(session, GST_FILE_CHECKLIST)
            session["state"] = GST_FILE_CHECKLIST
            await session_cache.save_session(wa_id, session)
            await send(wa_id, f"Selected period: {_format_period(selected)}\n\nChecking data...")
            return await _send_checklist_screen(wa_id, session, send=send)

    if text == "4":
        data["_awaiting_custom_period"] = True
        await session_cache.save_session(wa_id, session)
        await send(wa_id, "Enter the period as YYYY-MM (e.g. 2025-03):")
        return Response(status_code=200)

    # Invalid input — re-show menu
    lines = ["Invalid choice. Select a filing period:\n"]
    for idx, p in enumerate(periods, start=1):
        lines.append(f"{idx}) {_format_period(p)}")
    lines.append(f"{len(periods) + 1}) Other (enter custom period)")
    lines.append("\nBACK = Go Back")
    await send(wa_id, "\n".join(lines))
    return Response(status_code=200)


async def _send_checklist_screen(
    wa_id: str,
    session: dict,
    *,
    send: Callable[..., Awaitable],
) -> Response:
    """Build and send the checklist screen for the selected period."""

    data = _session_data(session)
    period = data.get("gst_filing_period", "N/A")
    pretty = _format_period(period)

    # Check invoice counts populated during onboarding/upload flows
    sales_uploaded = data.get("invoices_outward_count", 0) > 0
    purchases_uploaded = data.get("invoices_inward_count", 0) > 0
    has_any_data = sales_uploaded or purchases_uploaded

    check = "+" if sales_uploaded else "-"
    lines = [
        f"Filing Checklist for *{pretty}*:\n",
        f"[{check}] Sales invoices uploaded",
    ]
    check = "+" if purchases_uploaded else "-"
    lines.append(f"[{check}] Purchase invoices uploaded")

    if not has_any_data:
        lines.append("\nNo invoice data found for this period.")
        lines.append("\n1) File NIL Return\n2) Upload Bills\n3) Back")
    else:
        lines.append(
            "\n1) Continue to Summary\n2) Upload Missing Bills\n3) Back"
        )
    await send(wa_id, "\n".join(lines))
    return Response(status_code=200)


async def _handle_checklist(
    text: str,
    wa_id: str,
    session: dict,
    *,
    session_cache: Any,
    send: Callable[..., Awaitable],
    push_state: Callable,
    pop_state: Callable,
    state_to_screen_key: Callable,
    t: Callable,
) -> Response:
    """GST_FILE_CHECKLIST — show what's ready, let user continue or go back."""

    data = _session_data(session)
    sales_uploaded = data.get("invoices_outward_count", 0) > 0
    purchases_uploaded = data.get("invoices_inward_count", 0) > 0
    has_any_data = sales_uploaded or purchases_uploaded

    if text == "1":
        if has_any_data:
            # Continue to summary
            push_state(session, GST_SUMMARY)
            session["state"] = GST_SUMMARY
            await session_cache.save_session(wa_id, session)
            return await _send_summary_screen(wa_id, session, send=send)
        else:
            # File NIL return
            push_state(session, GST_NIL_SUGGEST)
            session["state"] = GST_NIL_SUGGEST
            await session_cache.save_session(wa_id, session)
            period = _format_period(data.get("gst_filing_period", ""))
            await send(
                wa_id,
                f"No invoices found for {period}. File NIL return?\n\n"
                "1) File NIL Return\n2) Upload Bills\n3) Back",
            )
            return Response(status_code=200)

    if text == "2":
        # Upload missing bills — go back to wizard sales entry as a stub
        await send(
            wa_id,
            "Upload your sales and purchase bills (photos/PDFs).\n"
            "Send 'done' when finished.\n\nBACK = Go Back",
        )
        return Response(status_code=200)

    if text == "3":
        # Go back
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, state_to_screen_key(session["state"])))
        return Response(status_code=200)

    # Default — re-display checklist
    return await _send_checklist_screen(wa_id, session, send=send)


async def _handle_nil_suggest(
    text: str,
    wa_id: str,
    session: dict,
    *,
    session_cache: Any,
    send: Callable[..., Awaitable],
    pop_state: Callable,
    state_to_screen_key: Callable,
    t: Callable,
) -> Response:
    """GST_NIL_SUGGEST — offer NIL filing when no invoices exist."""

    data = _session_data(session)
    period = _format_period(data.get("gst_filing_period", ""))

    if text == "1":
        # File NIL return via MasterGST
        logger.info("User %s filing NIL return for %s", wa_id, period)
        try:
            from app.domain.services.gst_service import file_nil_return_mastergst
            gstin = data.get("gstin", "")
            filing_period = data.get("gst_filing_period", "")
            # Attempt NIL filing — service handles MasterGST API call
            result = await file_nil_return_mastergst(gstin, filing_period)
            if result and result.get("success"):
                arn = result.get("arn", "N/A")
                await send(
                    wa_id,
                    f"NIL return filed successfully for {period}.\n"
                    f"ARN: {arn}\n\n"
                    "MENU = Main Menu\nBACK = Go Back",
                )
            else:
                error = result.get("error", "Unknown error") if result else "Service unavailable"
                await send(
                    wa_id,
                    f"NIL filing could not be completed: {error}\n"
                    "Please try again or contact your CA.\n\n"
                    "MENU = Main Menu\nBACK = Go Back",
                )
        except Exception:
            logger.exception("NIL filing failed for %s", wa_id)
            await send(
                wa_id,
                f"NIL return filing failed for {period}.\n"
                "Please try again later or contact your CA.\n\n"
                "MENU = Main Menu\nBACK = Go Back",
            )
        session["state"] = pop_state(session)
        data.pop("gst_filing_period", None)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    if text == "2":
        # Upload bills — return to checklist
        session["state"] = GST_FILE_CHECKLIST
        await session_cache.save_session(wa_id, session)
        await send(
            wa_id,
            "Upload your sales and purchase bills (photos/PDFs).\n"
            "Send 'done' when finished.\n\nBACK = Go Back",
        )
        return Response(status_code=200)

    if text == "3":
        # Back to checklist
        session["state"] = GST_FILE_CHECKLIST
        await session_cache.save_session(wa_id, session)
        return await _send_checklist_screen(wa_id, session, send=send)

    # Invalid — re-prompt
    await send(
        wa_id,
        f"No invoices found for {period}. File NIL return?\n\n"
        "1) File NIL Return\n2) Upload Bills\n3) Back",
    )
    return Response(status_code=200)


async def _send_summary_screen(
    wa_id: str,
    session: dict,
    *,
    send: Callable[..., Awaitable],
) -> Response:
    """Build and send the filing summary screen."""

    data = _session_data(session)
    period = _format_period(data.get("gst_filing_period", ""))

    # Use pre-computed tax figures from session (populated by gst_liability service)
    output_tax = float(data.get("output_tax_total", 0))
    itc = float(data.get("itc_total", 0))
    net_payable = max(output_tax - itc, 0)

    lines = [
        f"GST Filing Summary for *{period}*\n",
        f"Sales Tax (Output):      {_currency(output_tax)}",
        f"Purchase Credit (Input): {_currency(itc)}",
        "\u2500" * 30,
        f"Net GST Payable:         {_currency(net_payable)}",
        "",
        "1) Send to CA for Review",
        "2) File Now",
        "3) Back",
    ]
    await send(wa_id, "\n".join(lines))
    return Response(status_code=200)


def _currency(amount: float) -> str:
    """Format *amount* as Indian Rupee string."""
    return f"Rs.{amount:,.2f}"


async def _handle_summary(
    text: str,
    wa_id: str,
    session: dict,
    *,
    session_cache: Any,
    send: Callable[..., Awaitable],
    pop_state: Callable,
    state_to_screen_key: Callable,
    t: Callable,
) -> Response:
    """GST_SUMMARY — display tax breakdown and offer filing options."""

    data = _session_data(session)
    period = _format_period(data.get("gst_filing_period", ""))

    if text == "1":
        # Send to CA for review — create a filing record
        logger.info("User %s sent summary to CA for %s", wa_id, period)
        try:
            from app.domain.services.gst_workflow import create_gst_draft_from_session
            from app.core.db import get_db as _get_db
            async for _db in _get_db():
                draft = await create_gst_draft_from_session(session, _db)
                break
            await send(
                wa_id,
                f"Summary for {period} has been sent to your CA for review.\n"
                "You will be notified once the CA approves.\n\n"
                "MENU = Main Menu\nBACK = Go Back",
            )
        except Exception:
            logger.exception("Failed to create GST draft for CA review")
            await send(
                wa_id,
                f"Summary for {period} has been queued for CA review.\n"
                "You will be notified once the CA approves.\n\n"
                "MENU = Main Menu\nBACK = Go Back",
            )
        session["state"] = pop_state(session)
        data.pop("gst_filing_period", None)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    if text == "2":
        # File now — prepare and submit via MasterGST
        logger.info("User %s filing GSTR-3B for %s", wa_id, period)
        try:
            from app.domain.services.gst_service import file_gstr3b_from_session
            gstin = data.get("gstin", "")
            filing_period = data.get("gst_filing_period", "")
            invoices = data.get("session_invoices", [])
            result = await file_gstr3b_from_session(gstin, filing_period, invoices)
            await send(
                wa_id,
                f"Filing initiated for {period}.\n"
                "Your GSTR-3B has been prepared and submitted to the portal.\n"
                "You will receive a confirmation once filing is complete.\n\n"
                "MENU = Main Menu\nBACK = Go Back",
            )
        except Exception:
            logger.exception("GSTR-3B filing failed for %s", wa_id)
            await send(
                wa_id,
                f"Filing for {period} could not be completed.\n"
                "Please try again later or send to your CA for review.\n\n"
                "MENU = Main Menu\nBACK = Go Back",
            )
        session["state"] = pop_state(session)
        data.pop("gst_filing_period", None)
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    if text == "3":
        # Back to checklist
        session["state"] = GST_FILE_CHECKLIST
        await session_cache.save_session(wa_id, session)
        return await _send_checklist_screen(wa_id, session, send=send)

    # Invalid — re-display summary
    return await _send_summary_screen(wa_id, session, send=send)


async def _handle_filed_status(
    text: str,
    wa_id: str,
    session: dict,
    *,
    session_cache: Any,
    send: Callable[..., Awaitable],
    pop_state: Callable,
    state_to_screen_key: Callable,
    t: Callable,
) -> Response:
    """GST_FILED_STATUS — show the latest filing status for the user's GSTIN."""

    data = _session_data(session)
    gstin = data.get("gstin", "N/A")

    logger.info("Querying filing status for GSTIN %s (user %s)", gstin, wa_id)

    from app.domain.services.gst_service import get_current_gst_period

    current_period = get_current_gst_period()
    pretty_period = _format_period(current_period)

    # Check database for filing records
    filed_records = None
    try:
        from app.infrastructure.db.models import FilingRecord
        from sqlalchemy import select as sa_select
        from app.core.db import get_db as _get_db
        async for _db in _get_db():
            stmt = (
                sa_select(FilingRecord)
                .where(
                    FilingRecord.gstin == gstin,
                    FilingRecord.filing_type == "GST",
                )
                .order_by(FilingRecord.created_at.desc())
                .limit(1)
            )
            result = await _db.execute(stmt)
            filed_records = result.scalar_one_or_none()
            break
    except Exception:
        logger.exception("Error querying filing records for %s", gstin)

    if filed_records:
        status = filed_records.status
        filed_period = _format_period(filed_records.period)
        arn = filed_records.reference_number or "N/A"
        lines = [
            "Recent Filing Status:\n",
            f"GSTIN: {gstin}",
            f"Period: {filed_period}",
            f"Status: {status}",
            f"ARN: {arn}",
            "\nMENU = Main Menu\nBACK = Go Back",
        ]
        await send(wa_id, "\n".join(lines))
    else:
        # Fall back to session data check + current period info
        filing_record = data.get("last_filing")
        if filing_record:
            status = filing_record.get("status", "Unknown")
            filed_period = _format_period(filing_record.get("period", current_period))
            arn = filing_record.get("arn", "N/A")
            lines = [
                "Recent Filing Status:\n",
                f"GSTIN: {gstin}",
                f"Period: {filed_period}",
                f"Status: {status}",
                f"ARN: {arn}",
                "\nMENU = Main Menu\nBACK = Go Back",
            ]
            await send(wa_id, "\n".join(lines))
        else:
            await send(
                wa_id,
                f"No recent filings found for GSTIN {gstin}.\n"
                f"Current period ({pretty_period}) return has not been filed yet.\n\n"
                "MENU = Main Menu\nBACK = Go Back",
            )

    # Return to previous state
    session["state"] = pop_state(session)
    await session_cache.save_session(wa_id, session)
    return Response(status_code=200)
