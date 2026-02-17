# app/domain/services/deadline_scheduler.py
"""
Scheduled filing deadline reminder service.

Runs periodically (e.g., daily) and sends proactive WhatsApp reminders
to users whose sessions are active, notifying them of upcoming GST/ITR
filing deadlines.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import redis.asyncio as redis

from app.core.config import settings
from app.domain.i18n import t as i18n_t
from app.domain.services.tax_analytics import get_filing_deadlines
from app.infrastructure.external.whatsapp_client import send_whatsapp_text

logger = logging.getLogger("deadline_scheduler")

# How many days before the deadline to start reminding
REMINDER_THRESHOLDS = [7, 3, 1, 0]  # 7 days, 3 days, 1 day, and on the day

# Key prefix in Redis for tracking sent reminders (avoid duplicate sends)
REMINDER_SENT_PREFIX = "wa:reminder:"

# How often the scheduler loop runs (in seconds)
CHECK_INTERVAL_SECONDS = 6 * 3600  # Every 6 hours


async def _get_active_sessions(redis_url: str) -> list[dict]:
    """
    Scan Redis for all active WhatsApp sessions.
    Returns list of dicts with wa_id and lang.
    """
    import json

    r = redis.from_url(redis_url, decode_responses=True)
    sessions = []
    try:
        cursor = "0"
        while True:
            cursor, keys = await r.scan(cursor=cursor, match="wa:session:*", count=100)
            if keys:
                # Batch fetch with MGET instead of individual GETs
                values = await r.mget(keys)
                for key, raw in zip(keys, values):
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                        # Extract wa_id from key: "wa:session:{wa_id}"
                        wa_id = key.split(":", 2)[-1] if key.startswith("wa:session:") else None
                        if wa_id:
                            sessions.append({
                                "wa_id": wa_id,
                                "lang": data.get("lang", "en"),
                            })
                    except Exception:
                        continue
            if cursor == "0" or cursor == 0:
                break
    finally:
        await r.aclose()

    return sessions


async def _was_reminder_sent(
    r: redis.Redis, wa_id: str, form_name: str, due_date: date
) -> bool:
    """Check if we already sent this specific reminder."""
    key = f"{REMINDER_SENT_PREFIX}{wa_id}:{form_name}:{due_date}"
    return await r.exists(key) > 0


async def _mark_reminder_sent(
    r: redis.Redis, wa_id: str, form_name: str, due_date: date
) -> None:
    """Mark a reminder as sent, with a TTL of 30 days."""
    key = f"{REMINDER_SENT_PREFIX}{wa_id}:{form_name}:{due_date}"
    await r.set(key, "1", ex=30 * 24 * 3600)


async def send_deadline_reminders() -> int:
    """
    Check all active user sessions and send deadline reminders.

    Returns the number of reminders sent.
    """
    if not settings.REDIS_URL:
        logger.warning("REDIS_URL not configured — skipping deadline reminders")
        return 0

    sessions = await _get_active_sessions(settings.REDIS_URL)
    if not sessions:
        logger.info("No active sessions found — no reminders to send")
        return 0

    deadlines = get_filing_deadlines()
    if not deadlines:
        return 0

    # Filter deadlines that qualify for reminders
    today = date.today()
    actionable_deadlines = []
    for dl in deadlines:
        if dl.days_remaining < 0:
            # Overdue — always remind
            actionable_deadlines.append(dl)
        elif dl.days_remaining in REMINDER_THRESHOLDS or dl.days_remaining <= 3:
            # Approaching deadline
            actionable_deadlines.append(dl)

    if not actionable_deadlines:
        logger.info("No actionable deadlines for reminders today")
        return 0

    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    sent_count = 0

    try:
        for user_session in sessions:
            wa_id = user_session["wa_id"]
            lang = user_session.get("lang", "en")

            for dl in actionable_deadlines:
                # Check if already sent
                already_sent = await _was_reminder_sent(
                    r, wa_id, dl.form_name, dl.due_date
                )
                if already_sent:
                    continue

                # Build reminder message
                if dl.days_remaining < 0:
                    msg = i18n_t(
                        "DEADLINE_OVERDUE",
                        lang,
                        form_name=dl.form_name,
                        period=dl.period,
                        due_date=str(dl.due_date),
                        days_overdue=abs(dl.days_remaining),
                    )
                else:
                    msg = i18n_t(
                        "DEADLINE_REMINDER",
                        lang,
                        form_name=dl.form_name,
                        period=dl.period,
                        due_date=str(dl.due_date),
                        days_remaining=dl.days_remaining,
                    )

                try:
                    await send_whatsapp_text(wa_id, msg)
                    await _mark_reminder_sent(r, wa_id, dl.form_name, dl.due_date)
                    sent_count += 1
                    logger.info(
                        "Sent %s reminder to %s (due: %s, days: %d)",
                        dl.form_name,
                        wa_id,
                        dl.due_date,
                        dl.days_remaining,
                    )
                except Exception:
                    logger.exception(
                        "Failed to send reminder to %s for %s",
                        wa_id,
                        dl.form_name,
                    )
    finally:
        await r.aclose()

    logger.info("Deadline reminder run complete: %d reminders sent", sent_count)
    return sent_count


async def send_nil_filing_nudges() -> int:
    """
    Proactively nudge users who have a GSTIN but no invoices uploaded
    when a GST deadline is approaching. Suggests filing a NIL return.

    Returns the number of nudges sent.
    """
    if not settings.REDIS_URL:
        return 0

    import json as _json

    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    sent_count = 0

    try:
        deadlines = get_filing_deadlines()
        # Only nudge for GSTR-3B deadlines that are 5 days away or less
        gst_deadlines = [
            d for d in deadlines
            if "GSTR-3B" in d.form_name
            and 0 <= d.days_remaining <= 5
        ]
        if not gst_deadlines:
            return 0

        sessions = await _get_active_sessions(settings.REDIS_URL)

        for user_session in sessions:
            wa_id = user_session["wa_id"]
            lang = user_session.get("lang", "en")

            # Read full session data to check for GSTIN and invoices
            raw = await r.get(f"wa:session:{wa_id}")
            if not raw:
                continue
            try:
                session_data = _json.loads(raw)
            except Exception:
                continue

            data = session_data.get("data", {})
            gstin = data.get("gstin")
            invoices = data.get("uploaded_invoices", [])

            # Only nudge if user has GSTIN set but NO invoices
            if not gstin or invoices:
                continue

            for dl in gst_deadlines:
                nudge_key = f"{REMINDER_SENT_PREFIX}nil_nudge:{wa_id}:{dl.form_name}:{dl.due_date}"
                already_sent = await r.exists(nudge_key) > 0
                if already_sent:
                    continue

                msg = i18n_t(
                    "NIL_FILING_PROACTIVE_NUDGE",
                    lang,
                    period=dl.period,
                    due_date=str(dl.due_date),
                    days_remaining=dl.days_remaining,
                )

                try:
                    await send_whatsapp_text(wa_id, msg)
                    await r.set(nudge_key, "1", ex=30 * 24 * 3600)
                    sent_count += 1
                    logger.info(
                        "Sent NIL filing nudge to %s (GSTIN: %s, due: %s)",
                        wa_id,
                        gstin,
                        dl.due_date,
                    )
                except Exception:
                    logger.exception(
                        "Failed to send NIL nudge to %s for %s",
                        wa_id,
                        dl.form_name,
                    )
    finally:
        await r.aclose()

    if sent_count:
        logger.info("NIL filing nudge run: %d nudges sent", sent_count)
    return sent_count


async def start_deadline_reminder_loop() -> None:
    """
    Long-running loop that periodically checks and sends deadline reminders.
    Call this once at app startup (via FastAPI lifespan).
    """
    logger.info(
        "Starting deadline reminder loop (interval: %ds)",
        CHECK_INTERVAL_SECONDS,
    )
    while True:
        try:
            count = await send_deadline_reminders()
            if count > 0:
                logger.info("Sent %d deadline reminders this cycle", count)
        except Exception:
            logger.exception("Deadline reminder loop error")

        try:
            nudge_count = await send_nil_filing_nudges()
            if nudge_count > 0:
                logger.info("Sent %d NIL filing nudges this cycle", nudge_count)
        except Exception:
            logger.exception("NIL filing nudge loop error")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
