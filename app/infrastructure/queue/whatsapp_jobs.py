# app/infrastructure/queue/whatsapp_jobs.py

from datetime import datetime, timezone

from arq.connections import ArqRedis
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.infrastructure.db.models import WhatsAppDeadLetter, WhatsAppMessageLog

MAX_WHATSAPP_RETRIES = 3


async def send_whatsapp_job(
    ctx: dict, to_number: str, text: str, attempt: int = 1
) -> None:
    """
    Arq job: send WhatsApp message with retries + dead-letter logging.
    This is executed by the Arq worker, NOT by FastAPI directly.
    """
    logger.info(
        "Arq job send_whatsapp_job: to={} attempt={} text={!r}",
        to_number,
        attempt,
        text[:120],
    )

    async with AsyncSessionLocal() as db:  # type: AsyncSession
        try:
            success, error_message = await send_whatsapp_text_http(to_number, text)

            if success:
                logger.success("WhatsApp message sent successfully to {}", to_number)
                await _log_message(
                    db,
                    to_number=to_number,
                    text=text,
                    status="sent",
                    error=None,
                )
                await db.commit()
                return

            # Not successful but no exception (e.g. 400/401)
            logger.warning(
                "WhatsApp send failed to {} on attempt {}: {}",
                to_number,
                attempt,
                error_message,
            )

            await _log_message(
                db,
                to_number=to_number,
                text=text,
                status="failed",
                error=error_message,
            )
            await db.commit()

            if attempt < MAX_WHATSAPP_RETRIES:
                redis: ArqRedis = ctx["redis"]
                await redis.enqueue_job(
                    "send_whatsapp_job",
                    to_number,
                    text,
                    attempt + 1,
                )
                logger.info(
                    "Re-enqueued WhatsApp message for {} attempt {}",
                    to_number,
                    attempt + 1,
                )
            else:
                await _write_dead_letter(
                    db,
                    to_number=to_number,
                    text=text,
                    failure_reason="max_retries_exceeded",
                    last_error=error_message,
                    retry_count=attempt,
                )
                await db.commit()
                logger.error(
                    "Message moved to dead-letter after {} attempts for {}",
                    attempt,
                    to_number,
                )

        except Exception as e:
            logger.exception(
                "Exception in send_whatsapp_job for {} attempt {}: {}",
                to_number,
                attempt,
                e,
            )
            if attempt < MAX_WHATSAPP_RETRIES:
                redis: ArqRedis = ctx["redis"]
                await redis.enqueue_job(
                    "send_whatsapp_job",
                    to_number,
                    text,
                    attempt + 1,
                )
            else:
                await _write_dead_letter(
                    db,
                    to_number=to_number,
                    text=text,
                    failure_reason="exception",
                    last_error=str(e),
                    retry_count=attempt,
                )
                await db.commit()


async def _log_message(
    db: AsyncSession,
    to_number: str,
    text: str,
    status: str,
    error: str | None,
) -> None:
    log = WhatsAppMessageLog(
        to_number=to_number,
        text=text,
        status=status,
        error=error,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)


async def _write_dead_letter(
    db: AsyncSession,
    to_number: str,
    text: str,
    failure_reason: str,
    last_error: str | None,
    retry_count: int,
) -> None:
    dl = WhatsAppDeadLetter(
        to_number=to_number,
        text=text,
        failure_reason=failure_reason,
        last_error=last_error,
        retry_count=retry_count,
        created_at=datetime.now(timezone.utc),
    )
    db.add(dl)
