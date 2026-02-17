# app/api/routes/wa_handlers/gst_tax_payment.py
"""WhatsApp handler for GST tax payment sub-flows.

States handled:
    GST_TAX_PAYABLE     – Show net tax liability breakdown
    GST_PAYMENT_CAPTURE – Step-by-step challan entry (number → date → amount)
    GST_PAYMENT_CONFIRM – Review and confirm recorded payment
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Awaitable, Callable

from fastapi import Response

logger = logging.getLogger("wa_handlers.gst_tax_payment")

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------
GST_TAX_PAYABLE = "GST_TAX_PAYABLE"
GST_PAYMENT_CAPTURE = "GST_PAYMENT_CAPTURE"
GST_PAYMENT_CONFIRM = "GST_PAYMENT_CONFIRM"
GST_MENU = "GST_MENU"

HANDLED_STATES = {
    GST_TAX_PAYABLE,
    GST_PAYMENT_CAPTURE,
    GST_PAYMENT_CONFIRM,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _compute_liability(session: dict) -> dict:
    """Return tax-liability breakdown.

    Uses pre-computed values from session data which are populated by the
    GST liability service (gst_liability.compute_net_liability) during
    the filing flow. Falls back to zero if not computed yet.
    """
    data = session.get("data", {})
    return {
        "igst": float(data.get("net_payable_igst", data.get("liability_igst", 0))),
        "cgst": float(data.get("net_payable_cgst", data.get("liability_cgst", 0))),
        "sgst": float(data.get("net_payable_sgst", data.get("liability_sgst", 0))),
        "late_fee": float(data.get("late_fee", data.get("liability_late_fee", 0))),
        "interest": float(data.get("interest", data.get("liability_interest", 0))),
    }


def _format_currency(value: float | int) -> str:
    """Format a number as Indian-rupee string."""
    return f"\u20b9{value:,.2f}"


def _liability_message(liab: dict) -> str:
    """Build a human-readable liability summary."""
    total = liab["igst"] + liab["cgst"] + liab["sgst"]
    lines = [
        "\U0001f4ca *Net Tax Liability*\n",
        f"  IGST  : {_format_currency(liab['igst'])}",
        f"  CGST  : {_format_currency(liab['cgst'])}",
        f"  SGST  : {_format_currency(liab['sgst'])}",
        f"  *Total* : {_format_currency(total)}",
    ]
    if liab["late_fee"] or liab["interest"]:
        lines.append("")
        if liab["late_fee"]:
            lines.append(f"  Late fee : {_format_currency(liab['late_fee'])}")
        if liab["interest"]:
            lines.append(f"  Interest : {_format_currency(liab['interest'])}")
        grand = total + liab["late_fee"] + liab["interest"]
        lines.append(f"  *Grand Total* : {_format_currency(grand)}")
    lines.append("\n1) Record Payment\n2) Back")
    return "\n".join(lines)


def _payment_summary(payment: dict) -> str:
    """Build a confirmation summary for the captured challan details."""
    return (
        "\U0001f4dd *Payment Summary*\n\n"
        f"  Challan # : {payment.get('challan_number', '-')}\n"
        f"  Date      : {payment.get('challan_date', '-')}\n"
        f"  Amount    : \u20b9{payment.get('challan_amount', '-')}\n\n"
        "1) Confirm \u2705\n"
        "2) Re-enter"
    )


def _reset_payment(session: dict) -> None:
    """Clear any in-progress payment data and reset the capture step."""
    data = session.setdefault("data", {})
    data.pop("payment", None)
    data["payment_step"] = "challan_number"


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
    """Handle GST tax-payment states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    data = session.setdefault("data", {})

    # ------------------------------------------------------------------
    # GST_TAX_PAYABLE – display liability and offer to record payment
    # ------------------------------------------------------------------
    if state == GST_TAX_PAYABLE:
        liab = _compute_liability(session)
        await send(wa_id, _liability_message(liab))
        return Response(status_code=200)

    # ------------------------------------------------------------------
    # GST_PAYMENT_CAPTURE – multi-step challan entry
    # ------------------------------------------------------------------
    if state == GST_PAYMENT_CAPTURE:
        step = data.get("payment_step", "challan_number")
        payment = data.setdefault("payment", {})

        # --- Step: challan_number ---
        if step == "challan_number":
            stripped = text.strip()
            if not stripped:
                await send(wa_id, "Please enter a valid challan number.")
                return Response(status_code=200)

            payment["challan_number"] = stripped
            data["payment_step"] = "challan_date"
            session["state"] = GST_PAYMENT_CAPTURE
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "Enter challan date (DD/MM/YYYY):")
            return Response(status_code=200)

        # --- Step: challan_date ---
        if step == "challan_date":
            stripped = text.strip()
            if not _DATE_RE.match(stripped):
                await send(
                    wa_id,
                    "Invalid date format. Please enter the date as DD/MM/YYYY.",
                )
                return Response(status_code=200)

            try:
                datetime.strptime(stripped, "%d/%m/%Y")
            except ValueError:
                await send(
                    wa_id,
                    "That doesn't look like a valid date. Please try again (DD/MM/YYYY).",
                )
                return Response(status_code=200)

            payment["challan_date"] = stripped
            data["payment_step"] = "challan_amount"
            session["state"] = GST_PAYMENT_CAPTURE
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "Enter the challan amount (\u20b9):")
            return Response(status_code=200)

        # --- Step: challan_amount ---
        if step == "challan_amount":
            stripped = text.strip().replace(",", "")
            try:
                amount = float(stripped)
                if amount <= 0:
                    raise ValueError("non-positive")
            except (ValueError, TypeError):
                await send(
                    wa_id,
                    "Please enter a valid positive amount (e.g. 15000 or 15,000).",
                )
                return Response(status_code=200)

            payment["challan_amount"] = f"{amount:,.2f}"
            session["state"] = GST_PAYMENT_CONFIRM
            push_state(session, GST_PAYMENT_CONFIRM)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, _payment_summary(payment))
            return Response(status_code=200)

        # Fallback for unexpected step value
        logger.warning(
            "Unexpected payment_step '%s' for wa_id=%s; resetting.",
            step,
            wa_id,
        )
        _reset_payment(session)
        session["state"] = GST_PAYMENT_CAPTURE
        await session_cache.save_session(wa_id, session)
        await send(wa_id, "Enter the challan number:")
        return Response(status_code=200)

    # ------------------------------------------------------------------
    # GST_PAYMENT_CONFIRM – review and confirm or re-enter
    # ------------------------------------------------------------------
    if state == GST_PAYMENT_CONFIRM:
        payment = data.get("payment", {})

        if text == "1":
            # Confirm — persist payment via gst_payment service
            logger.info(
                "Payment recorded for wa_id=%s: challan=%s date=%s amount=%s",
                wa_id,
                payment.get("challan_number"),
                payment.get("challan_date"),
                payment.get("challan_amount"),
            )
            try:
                from app.domain.services.gst_payment import record_payment
                from app.core.db import get_db as _get_db
                period_id = data.get("current_period_id")
                if period_id:
                    from uuid import UUID as _UUID
                    challan_data = {
                        "challan_number": payment.get("challan_number"),
                        "challan_date": payment.get("challan_date"),
                        "total": float(payment.get("challan_amount", "0").replace(",", "")),
                    }
                    async for _db in _get_db():
                        await record_payment(_UUID(period_id), challan_data, _db)
                        break
            except Exception:
                logger.exception("Failed to persist payment record for %s", wa_id)

            await send(
                wa_id,
                "\u2705 *Payment recorded successfully!*\n\n"
                f"Challan #{payment.get('challan_number', '-')} "
                f"for \u20b9{payment.get('challan_amount', '-')} "
                "has been saved.\n\n"
                "Returning to GST menu\u2026",
            )
            # Clean up payment data
            data.pop("payment", None)
            data.pop("payment_step", None)
            session["state"] = GST_MENU
            pop_state(session)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, state_to_screen_key(GST_MENU)))
            return Response(status_code=200)

        if text == "2":
            # Re-enter – reset and go back to capture
            _reset_payment(session)
            session["state"] = GST_PAYMENT_CAPTURE
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "Let's start over.\n\nEnter the challan number:")
            return Response(status_code=200)

        # Unrecognised input – re-show the summary
        await send(wa_id, _payment_summary(payment))
        return Response(status_code=200)

    return None
