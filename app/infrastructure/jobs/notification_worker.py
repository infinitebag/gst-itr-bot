# app/infrastructure/jobs/notification_worker.py
"""
Background notification worker for proactive WhatsApp template messages.

Periodically checks for pending notifications and sends them via WhatsApp.
Also schedules new filing deadline reminders daily.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.core.config import settings

logger = logging.getLogger("notification_worker")

_worker_task: asyncio.Task | None = None


async def _run_notification_cycle() -> None:
    """Run one cycle: process pending notifications."""
    try:
        from app.core.db import get_db as _get_db
        from app.domain.services.notification_service import (
            process_pending_notifications,
            schedule_filing_reminders,
        )

        async for db in _get_db():
            # 1. Send any pending notifications
            sent = await process_pending_notifications(db)
            if sent > 0:
                logger.info("Sent %d notifications", sent)

            # 2. Schedule new reminders (idempotent — skips if already scheduled)
            scheduled = await schedule_filing_reminders(db)
            if scheduled > 0:
                logger.info("Scheduled %d new filing reminders", scheduled)

            await db.commit()
            break
    except Exception:
        logger.exception("Notification cycle error")


async def _notification_loop() -> None:
    """Infinite loop that runs notification cycles at the configured interval."""
    interval = settings.NOTIFICATION_CHECK_INTERVAL_SECONDS
    logger.info("Notification worker started (interval=%ds)", interval)

    while True:
        try:
            await _run_notification_cycle()
        except asyncio.CancelledError:
            logger.info("Notification worker cancelled")
            break
        except Exception:
            logger.exception("Notification worker unexpected error")

        await asyncio.sleep(interval)


def start_notification_worker() -> None:
    """Start the background notification worker task.

    Safe to call multiple times — only starts one worker.
    """
    global _worker_task

    if not settings.NOTIFICATION_ENABLED:
        logger.info("Notifications disabled — worker not started")
        return

    if _worker_task is not None and not _worker_task.done():
        logger.debug("Notification worker already running")
        return

    _worker_task = asyncio.create_task(_notification_loop())
    logger.info("Notification worker task created")


def stop_notification_worker() -> None:
    """Cancel the background notification worker."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        _worker_task.cancel()
        logger.info("Notification worker stopped")
    _worker_task = None
