# app/api/routes/wa_handlers/gst_credit_check.py
"""Medium-segment credit check handler (Phase 7B).

States handled:
    MEDIUM_CREDIT_CHECK, MEDIUM_CREDIT_RESULT, GST_FILING_STATUS
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.gst_credit_check")

# State constants
MEDIUM_CREDIT_CHECK = "MEDIUM_CREDIT_CHECK"
MEDIUM_CREDIT_RESULT = "MEDIUM_CREDIT_RESULT"
GST_FILING_STATUS = "GST_FILING_STATUS"
GST_PERIOD_MENU = "GST_PERIOD_MENU"

HANDLED_STATES = {
    MEDIUM_CREDIT_CHECK,
    MEDIUM_CREDIT_RESULT,
    GST_FILING_STATUS,
}


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
    """Handle medium-segment credit check states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    if state == MEDIUM_CREDIT_CHECK:
        from app.domain.services.gst_service import get_current_gst_period

        gstin = session.get("data", {}).get("gstin", "")
        period = session.get("data", {}).get("period") or get_current_gst_period()
        await send(wa_id, "🔄 Running credit check... Importing purchase data and matching invoices.")
        matched = 0
        mismatched = 0
        additional_credit = "₹0"
        try:
            from app.core.db import get_db as _get_db
            from app.infrastructure.db.repositories.return_period_repository import (
                ReturnPeriodRepository,
            )
            from sqlalchemy import select as sa_select
            from app.infrastructure.db.models import User as UserModel

            async for db in _get_db():
                user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                user_result = await db.execute(user_stmt)
                user = user_result.scalar_one_or_none()
                if user:
                    rp_repo = ReturnPeriodRepository(db)
                    rp = await rp_repo.create_or_get(user.id, gstin, period)

                    from app.domain.services.gstr2b_service import import_gstr2b

                    await import_gstr2b(
                        user_id=user.id,
                        gstin=gstin,
                        period=period,
                        period_id=rp.id,
                        db=db,
                    )

                    from app.domain.services.gst_reconciliation import reconcile_period

                    summary = await reconcile_period(rp.id, db)

                    matched = summary.matched
                    mismatched = (
                        summary.value_mismatch + summary.missing_in_2b + summary.missing_in_books
                    )
                    additional_credit = f"₹{summary.missing_in_books_taxable:,.2f}"

                    session.setdefault("data", {})["credit_check"] = {
                        "matched": matched,
                        "mismatched": mismatched,
                        "value_mismatch": summary.value_mismatch,
                        "missing_in_2b": summary.missing_in_2b,
                        "missing_in_books": summary.missing_in_books,
                        "additional_credit": str(summary.missing_in_books_taxable),
                        "period_id": str(rp.id),
                    }
                else:
                    logger.warning("Credit check: user not found for %s", wa_id)
        except Exception as e:
            logger.exception("Credit check failed for %s", wa_id)
            await send(
                wa_id,
                f"⚠️ Credit check encountered an issue: {str(e)[:100]}. Showing available data.",
            )

        session["state"] = MEDIUM_CREDIT_RESULT
        await session_cache.save_session(wa_id, session)
        await send(
            wa_id,
            t(
                session,
                "CREDIT_CHECK_RESULT",
                matched=matched,
                mismatched=mismatched,
                additional_credit=additional_credit,
            ),
        )
        return Response(status_code=200)

    if state == MEDIUM_CREDIT_RESULT:
        from app.domain.services.gst_service import get_current_gst_period

        if text == "1":
            session["state"] = GST_PERIOD_MENU
            await session_cache.save_session(wa_id, session)
            gstin = session.get("data", {}).get("gstin", "")
            period = session.get("data", {}).get("period") or get_current_gst_period()
            await send(
                wa_id, t(session, "GST_PERIOD_MENU", period=period, gstin=gstin, status="draft")
            )
        elif text == "2":
            cc = session.get("data", {}).get("credit_check", {})
            val_mm = cc.get("value_mismatch", 0)
            miss_2b = cc.get("missing_in_2b", 0)
            miss_books = cc.get("missing_in_books", 0)
            lines = ["📊 *Mismatch Details:*\n"]
            if val_mm:
                lines.append(f"⚠️ Value mismatches: {val_mm} invoice(s)")
            if miss_2b:
                lines.append(f"📤 Missing in GSTR-2B (not from suppliers): {miss_2b} invoice(s)")
            if miss_books:
                lines.append(f"📥 In GSTR-2B but not in your books: {miss_books} invoice(s)")
            if not (val_mm or miss_2b or miss_books):
                lines.append("✅ No mismatches found — all invoices matched!")
            lines.append("\n1) Continue to filing\nMENU = Main Menu\nBACK = Go Back")
            await send(wa_id, "\n".join(lines))
        elif text == "3":
            miss_2b = session.get("data", {}).get("credit_check", {}).get("missing_in_2b", 0)
            if miss_2b:
                await send(
                    wa_id,
                    f"📨 Supplier notification for {miss_2b} missing invoice(s) will be sent. "
                    "This feature requires email/WhatsApp integration with your suppliers."
                    "\n\nMENU = Main Menu\nBACK = Go Back",
                )
            else:
                await send(
                    wa_id,
                    "✅ No missing invoices to notify suppliers about.\n\nMENU = Main Menu\nBACK = Go Back",
                )
        else:
            session["state"] = pop_state(session)
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, state_to_screen_key(session["state"])))
        return Response(status_code=200)

    if state == GST_FILING_STATUS:
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, state_to_screen_key(session["state"])))
        return Response(status_code=200)

    return None
