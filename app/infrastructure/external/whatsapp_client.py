import asyncio
import json
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.infrastructure.db.models import WhatsAppDeadLetter, WhatsAppMessageLog

# ----------------- CONFIG -----------------

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0

# Global rate limit: max X messages per second across this process
MIN_SECONDS_BETWEEN_MESSAGES = 0.25  # ~4 messages/sec

# Per-user rate limits
PER_USER_MAX_PER_MINUTE = 30  # tune as you like
PER_USER_MAX_PER_DAY = 1000  # tune as you like


# ----------------- QUEUE TYPES -----------------


@dataclass
class OutgoingMessage:
    to: str
    text: str
    attempt: int = 0


_outgoing_queue: "asyncio.Queue[OutgoingMessage]" = asyncio.Queue()

_last_send_ts: float = 0.0
_send_lock = asyncio.Lock()


# ----------------- PER-USER RATE STATE -----------------


@dataclass
class UserRateState:
    minute_window_start: float
    minute_count: int
    day_window_start: float
    day_count: int


# in-memory map: to_number -> UserRateState
_user_rate_state: dict[str, UserRateState] = {}


def _now_ts() -> float:
    return time.time()


def _get_user_rate_state(to_number: str) -> UserRateState:
    now = _now_ts()
    state = _user_rate_state.get(to_number)
    if state is None:
        state = UserRateState(
            minute_window_start=now,
            minute_count=0,
            day_window_start=now,
            day_count=0,
        )
        _user_rate_state[to_number] = state
    return state


def _update_and_check_user_rate(to_number: str) -> bool:
    """
    Update counters and return True if sending is allowed,
    False if user exceeded limit (per minute or per day).
    """
    now = _now_ts()
    state = _get_user_rate_state(to_number)

    # Reset minute window if needed
    if now - state.minute_window_start >= 60.0:
        state.minute_window_start = now
        state.minute_count = 0

    # Reset day window if needed (24 hours)
    if now - state.day_window_start >= 24 * 3600.0:
        state.day_window_start = now
        state.day_count = 0

    # Check future counts
    future_minute = state.minute_count + 1
    future_day = state.day_count + 1

    if future_minute > PER_USER_MAX_PER_MINUTE or future_day > PER_USER_MAX_PER_DAY:
        return False

    # Apply counts
    state.minute_count = future_minute
    state.day_count = future_day
    return True


# ----------------- PUBLIC API -----------------


async def send_whatsapp_text(to_number: str, text: str) -> None:
    """
    Public function used everywhere in your app.

    Now:
    - Checks per-user rate limits
    - If exceeded -> logs dead-letter and returns
    - Else enqueues message for async sending
    """
    if not _update_and_check_user_rate(to_number):
        # Rate limit exceeded, log dead-letter and drop
        # Rate limit exceeded, log dead-letter and drop
        reason = "per_user_rate_limit"
        msg = f"Rate limit exceeded: >{PER_USER_MAX_PER_MINUTE}/minute or >{PER_USER_MAX_PER_DAY}/day"
        await _log_dead_letter(
            to_number=to_number,
            text=text,
            failure_reason="per_user_rate_limit",
            last_error=f"Rate limit exceeded: >{PER_USER_MAX_PER_MINUTE}/minute or >{PER_USER_MAX_PER_DAY}/day",
            retry_count=0,
        )
        await _log_message(
            to_number=to_number,
            text=text,
            status="dropped_rate_limit",
            error=msg,
        )
        print(
            f"[WhatsAppWorker] Dropping message to {to_number} due to per-user rate limit."
        )
        return

    msg = OutgoingMessage(to=to_number, text=text)
    await _outgoing_queue.put(msg)


async def start_whatsapp_sender_worker() -> None:
    """
    Call this once at startup (FastAPI on_event('startup')).
    """
    print("[WhatsAppWorker] Starting sender worker...")

    while True:
        msg: OutgoingMessage = await _outgoing_queue.get()
        try:
            await _send_with_retries(msg)
        except Exception as e:
            print(f"[WhatsAppWorker] Giving up on message to {msg.to}: {e!r}")
        finally:
            _outgoing_queue.task_done()


# ----------------- INTERNAL HELPERS -----------------


async def _send_with_retries(msg: OutgoingMessage) -> None:
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await _rate_limited_send(msg.to, msg.text)
            return
        except Exception as e:
            print(f"[WhatsAppWorker] Send attempt {attempt} failed for {msg.to}: {e!r}")
            if attempt == MAX_RETRIES:
                # All retries failed -> dead-letter
                await _log_dead_letter(
                    to_number=msg.to,
                    text=msg.text,
                    failure_reason="max_retries_exceeded",
                    last_error=str(e),
                    retry_count=attempt,
                )
                print(
                    f"[WhatsAppWorker] MAX_RETRIES reached, logged dead-letter for {msg.to}"
                )
                return
            await asyncio.sleep(backoff)
            backoff *= 2


async def _rate_limited_send(to_number: str, text: str) -> None:
    """
    Global rate limiting across all users.
    """
    global _last_send_ts

    async with _send_lock:
        now = _now_ts()
        elapsed = now - _last_send_ts
        if elapsed < MIN_SECONDS_BETWEEN_MESSAGES:
            await asyncio.sleep(MIN_SECONDS_BETWEEN_MESSAGES - elapsed)

        _last_send_ts = _now_ts()

        await _send_whatsapp_http(to_number, text)


async def _send_whatsapp_http(to_number: str, text: str) -> None:
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = settings.WHATSAPP_ACCESS_TOKEN

    if not phone_number_id or not access_token:
        raise RuntimeError(
            "WhatsApp credentials not configured (PHONE_NUMBER_ID / ACCESS_TOKEN)."
        )

    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        print(
            f"❌ WhatsApp send error [{resp.status_code}] to {to_number}: {json.dumps(data)}"
        )
        raise RuntimeError(f"WhatsApp API error {resp.status_code}")
    else:
        try:
            data = resp.json()
        except Exception:
            data = {}
        print(
            f"✅ WhatsApp message sent to {to_number} (msg_id={data.get('messages', [{}])[0].get('id')})"
        )

        # NEW: log successful send
        await _log_message(
            to_number=to_number,
            text=text,
            status="sent",
            error=None,
        )


async def _log_dead_letter(
    to_number: str,
    text: str,
    failure_reason: str,
    last_error: str | None,
    retry_count: int,
) -> None:
    """
    Persist failed messages into DB so you can inspect / replay later.
    """
    try:
        async with AsyncSessionLocal() as session:
            dl = WhatsAppDeadLetter(
                to_number=to_number,
                text=text,
                failure_reason=failure_reason,
                last_error=last_error,
                retry_count=retry_count,
            )
            session.add(dl)
            await session.commit()
    except Exception as e:
        # Don't let DB errors break sending – just log
        print(f"[WhatsAppWorker] Failed to log dead-letter for {to_number}: {e!r}")


async def _log_message(
    to_number: str,
    text: str,
    status: str,
    error: str | None = None,
) -> None:
    """
    Log WhatsApp messages (sent or dropped) for usage stats.
    """
    try:
        async with AsyncSessionLocal() as session:
            row = WhatsAppMessageLog(
                to_number=to_number,
                text=text,
                status=status,
                error=error,
            )
            session.add(row)
            await session.commit()
    except Exception as e:
        print(f"[WhatsAppWorker] Failed to log message for {to_number}: {e!r}")
