import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.infrastructure.db.models import WhatsAppDeadLetter, WhatsAppMessageLog

logger = logging.getLogger("whatsapp_client")

GRAPH_API_VERSION = "v20.0"

# ----------------- CONFIG -----------------

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0

# Global rate limit: max X messages per second across this process
MIN_SECONDS_BETWEEN_MESSAGES = 0.25  # ~4 messages/sec

# Per-user rate limits
PER_USER_MAX_PER_MINUTE = 30
PER_USER_MAX_PER_DAY = 1000


# ----------------- QUEUE TYPES -----------------


@dataclass
class OutgoingMessage:
    to: str
    text: str
    attempt: int = 0
    # For interactive / template messages, store the full API payload.
    # When ``payload`` is set, ``_send_whatsapp_payload`` is used instead
    # of the text-only ``_send_whatsapp_http``.
    payload: dict | None = None


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
_user_rate_lock = asyncio.Lock()


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

    future_minute = state.minute_count + 1
    future_day = state.day_count + 1

    if future_minute > PER_USER_MAX_PER_MINUTE or future_day > PER_USER_MAX_PER_DAY:
        return False

    state.minute_count = future_minute
    state.day_count = future_day
    return True


# ----------------- PUBLIC API -----------------


async def send_whatsapp_text(to_number: str, text: str) -> None:
    """
    Public function used everywhere in the app.

    - Checks per-user rate limits
    - If exceeded -> logs dead-letter and returns
    - Else enqueues message for async sending
    """
    async with _user_rate_lock:
        rate_ok = _update_and_check_user_rate(to_number)
    if not rate_ok:
        error_msg = (
            f"Rate limit exceeded: >{PER_USER_MAX_PER_MINUTE}/minute "
            f"or >{PER_USER_MAX_PER_DAY}/day"
        )
        await _log_dead_letter(
            to_number=to_number,
            text=text,
            failure_reason="per_user_rate_limit",
            last_error=error_msg,
            retry_count=0,
        )
        await _log_message(
            to_number=to_number,
            text=text,
            status="dropped_rate_limit",
            error=error_msg,
        )
        logger.warning("Dropping message to %s due to per-user rate limit.", to_number)
        return

    msg = OutgoingMessage(to=to_number, text=text)
    await _outgoing_queue.put(msg)


async def start_whatsapp_sender_worker() -> None:
    """
    Call this once at startup (FastAPI lifespan).
    """
    logger.info("Starting sender worker...")

    while True:
        msg: OutgoingMessage = await _outgoing_queue.get()
        try:
            await _send_with_retries(msg)
        except Exception as e:
            logger.error("Giving up on message to %s: %r", msg.to, e)
        finally:
            _outgoing_queue.task_done()


# ----------------- INTERNAL HELPERS -----------------


async def _send_with_retries(msg: OutgoingMessage) -> None:
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await _rate_limited_send(msg.to, msg.text, payload=msg.payload)
            return
        except Exception as e:
            logger.warning(
                "Send attempt %d failed for %s: %r", attempt, msg.to, e
            )
            if attempt == MAX_RETRIES:
                await _log_dead_letter(
                    to_number=msg.to,
                    text=msg.text,
                    failure_reason="max_retries_exceeded",
                    last_error=str(e),
                    retry_count=attempt,
                )
                logger.error(
                    "MAX_RETRIES reached, logged dead-letter for %s", msg.to
                )
                return
            await asyncio.sleep(backoff)
            backoff *= 2


async def _rate_limited_send(to_number: str, text: str, *, payload: dict | None = None) -> None:
    global _last_send_ts

    async with _send_lock:
        now = _now_ts()
        elapsed = now - _last_send_ts
        if elapsed < MIN_SECONDS_BETWEEN_MESSAGES:
            await asyncio.sleep(MIN_SECONDS_BETWEEN_MESSAGES - elapsed)

        _last_send_ts = _now_ts()

        if payload is not None:
            await _send_whatsapp_payload(to_number, payload)
        else:
            await _send_whatsapp_http(to_number, text)


async def _send_whatsapp_http(to_number: str, text: str) -> None:
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = settings.WHATSAPP_ACCESS_TOKEN

    if not phone_number_id or not access_token:
        raise RuntimeError(
            "WhatsApp credentials not configured (PHONE_NUMBER_ID / ACCESS_TOKEN)."
        )

    url = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}"
        f"/{phone_number_id}/messages"
    )

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

        logger.error(
            "WhatsApp send error [%d] to %s: %s",
            resp.status_code,
            to_number,
            json.dumps(data),
        )
        raise RuntimeError(f"WhatsApp API error {resp.status_code}")
    else:
        try:
            data = resp.json()
        except Exception:
            data = {}
        msg_id = data.get("messages", [{}])[0].get("id")
        logger.info("WhatsApp message sent to %s (msg_id=%s)", to_number, msg_id)

        await _log_message(
            to_number=to_number,
            text=text,
            status="sent",
            error=None,
        )


async def _send_whatsapp_payload(to_number: str, payload: dict) -> None:
    """Send an arbitrary WhatsApp Cloud API payload (interactive / template).

    The caller is responsible for building the correct ``payload`` dict;
    this helper only adds ``messaging_product`` and ``to`` if missing,
    then POSTs to the Messages endpoint.
    """
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = settings.WHATSAPP_ACCESS_TOKEN

    if not phone_number_id or not access_token:
        raise RuntimeError(
            "WhatsApp credentials not configured (PHONE_NUMBER_ID / ACCESS_TOKEN)."
        )

    url = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}"
        f"/{phone_number_id}/messages"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Ensure required top-level fields
    payload.setdefault("messaging_product", "whatsapp")
    payload.setdefault("to", to_number)

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    log_text = json.dumps(payload, ensure_ascii=False)[:500]

    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        logger.error(
            "WhatsApp payload send error [%d] to %s: %s",
            resp.status_code,
            to_number,
            json.dumps(data),
        )
        raise RuntimeError(f"WhatsApp API error {resp.status_code}")
    else:
        try:
            data = resp.json()
        except Exception:
            data = {}
        msg_id = data.get("messages", [{}])[0].get("id")
        logger.info("WhatsApp payload sent to %s (msg_id=%s)", to_number, msg_id)

        await _log_message(
            to_number=to_number,
            text=log_text,
            status="sent",
            error=None,
        )


# ----------------- INTERACTIVE / TEMPLATE PUBLIC API -----------------


async def send_whatsapp_buttons(
    to_number: str,
    body: str,
    buttons: list[dict],
    *,
    header: str | None = None,
    footer: str | None = None,
) -> None:
    """Send an interactive *button* message (max 3 buttons).

    Parameters
    ----------
    to_number : str
        Recipient WhatsApp ID (phone number).
    body : str
        Main message body text.
    buttons : list[dict]
        Each dict must have ``id`` (≤256 chars) and ``title`` (≤20 chars).
        Example: ``[{"id": "btn_yes", "title": "✅ Yes"}]``
    header : str, optional
        Header text shown above body.
    footer : str, optional
        Footer text shown below body.
    """
    if len(buttons) > 3:
        raise ValueError("WhatsApp button messages support a maximum of 3 buttons")

    interactive: dict = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}}
                for btn in buttons
            ]
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": interactive,
    }

    # Rate-limit + enqueue the same way as text messages
    async with _user_rate_lock:
        rate_ok = _update_and_check_user_rate(to_number)
    if not rate_ok:
        error_msg = f"Rate limit exceeded for interactive button message"
        await _log_dead_letter(to_number=to_number, text=body, failure_reason="per_user_rate_limit", last_error=error_msg, retry_count=0)
        logger.warning("Dropping interactive button message to %s due to rate limit.", to_number)
        return

    msg = OutgoingMessage(to=to_number, text=body, payload=payload)
    await _outgoing_queue.put(msg)


async def send_whatsapp_list(
    to_number: str,
    body: str,
    sections: list[dict],
    *,
    button_text: str = "Choose",
    header: str | None = None,
    footer: str | None = None,
) -> None:
    """Send an interactive *list* message (max 10 rows across ≤10 sections).

    Parameters
    ----------
    to_number : str
        Recipient WhatsApp ID.
    body : str
        Main message body text.
    sections : list[dict]
        Each section: ``{"title": "...", "rows": [{"id": "...", "title": "...", "description": "..."}]}``
    button_text : str
        Text on the list open button (≤20 chars).  Default: "Choose".
    header : str, optional
        Header text.
    footer : str, optional
        Footer text.
    """
    interactive: dict = {
        "type": "list",
        "body": {"text": body},
        "action": {
            "button": button_text,
            "sections": sections,
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": interactive,
    }

    async with _user_rate_lock:
        rate_ok = _update_and_check_user_rate(to_number)
    if not rate_ok:
        error_msg = f"Rate limit exceeded for interactive list message"
        await _log_dead_letter(to_number=to_number, text=body, failure_reason="per_user_rate_limit", last_error=error_msg, retry_count=0)
        logger.warning("Dropping interactive list message to %s due to rate limit.", to_number)
        return

    msg = OutgoingMessage(to=to_number, text=body, payload=payload)
    await _outgoing_queue.put(msg)


async def send_whatsapp_template(
    to_number: str,
    template_name: str,
    language: str = "en",
    *,
    components: list[dict] | None = None,
) -> None:
    """Send a WhatsApp *template* message (pre-approved by Meta).

    Parameters
    ----------
    to_number : str
        Recipient WhatsApp ID.
    template_name : str
        Registered template name (e.g. ``"filing_reminder"``).
    language : str
        Template language code (e.g. ``"en"``, ``"hi"``).
    components : list[dict], optional
        Template components for variable substitution.
        Example: ``[{"type": "body", "parameters": [{"type": "text", "text": "Jan 2025"}]}]``
    """
    template: dict = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": template,
    }

    async with _user_rate_lock:
        rate_ok = _update_and_check_user_rate(to_number)
    if not rate_ok:
        error_msg = f"Rate limit exceeded for template message"
        await _log_dead_letter(to_number=to_number, text=f"[Template: {template_name}]", failure_reason="per_user_rate_limit", last_error=error_msg, retry_count=0)
        logger.warning("Dropping template message to %s due to rate limit.", to_number)
        return

    msg = OutgoingMessage(to=to_number, text=f"[Template: {template_name}]", payload=payload)
    await _outgoing_queue.put(msg)


async def _log_dead_letter(
    to_number: str,
    text: str,
    failure_reason: str,
    last_error: str | None,
    retry_count: int,
) -> None:
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
        logger.error("Failed to log dead-letter for %s: %r", to_number, e)


async def send_whatsapp_document(
    to_number: str,
    file_bytes: bytes,
    filename: str,
    caption: str = "",
) -> None:
    """
    Send a document (PDF, JSON, etc.) to a WhatsApp user.

    Steps:
    1. Upload the file to WhatsApp Media API.
    2. Send a document message with the uploaded media ID.
    """
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = settings.WHATSAPP_ACCESS_TOKEN

    if not phone_number_id or not access_token:
        raise RuntimeError(
            "WhatsApp credentials not configured (PHONE_NUMBER_ID / ACCESS_TOKEN)."
        )

    base_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}"

    # Step 1: Upload media
    upload_url = f"{base_url}/media"
    headers_upload = {
        "Authorization": f"Bearer {access_token}",
    }

    # Determine MIME type from filename
    if filename.endswith(".pdf"):
        mime_type = "application/pdf"
    elif filename.endswith(".json"):
        mime_type = "application/json"
    else:
        mime_type = "application/octet-stream"

    async with httpx.AsyncClient(timeout=30.0) as client:
        files = {
            "file": (filename, file_bytes, mime_type),
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type,
        }
        resp = await client.post(upload_url, headers=headers_upload, files=files, data=data)

    if resp.status_code >= 400:
        logger.error("WhatsApp media upload failed [%d]: %s", resp.status_code, resp.text)
        raise RuntimeError(f"WhatsApp media upload error {resp.status_code}")

    media_data = resp.json()
    media_id = media_data.get("id")
    if not media_id:
        raise RuntimeError(f"No media ID in upload response: {media_data}")

    logger.info("Uploaded media %s for %s", media_id, to_number)

    # Step 2: Send document message
    msg_url = f"{base_url}/messages"
    headers_msg = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
        },
    }
    if caption:
        payload["document"]["caption"] = caption

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(msg_url, headers=headers_msg, json=payload)

    if resp.status_code >= 400:
        logger.error("WhatsApp document send error [%d]: %s", resp.status_code, resp.text)
        raise RuntimeError(f"WhatsApp document send error {resp.status_code}")

    msg_id = resp.json().get("messages", [{}])[0].get("id")
    logger.info("WhatsApp document sent to %s (msg_id=%s, file=%s)", to_number, msg_id, filename)

    await _log_message(
        to_number=to_number,
        text=f"[Document: {filename}] {caption}",
        status="sent",
        error=None,
    )


async def _log_message(
    to_number: str,
    text: str,
    status: str,
    error: str | None = None,
) -> None:
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
        logger.error("Failed to log message for %s: %r", to_number, e)
