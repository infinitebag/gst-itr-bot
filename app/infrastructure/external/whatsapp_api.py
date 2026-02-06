# app/infrastructure/external/whatsapp_api.py

import httpx
from loguru import logger

from app.core.config import settings

WHATSAPP_API_BASE = "https://graph.facebook.com/v20.0"


async def send_whatsapp_text(to_number: str, text: str) -> None:
    """
    Low-level WhatsApp Cloud API sender.
    This is called only from background jobs (ARQ worker).
    """
    url = f"{WHATSAPP_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "text": {"body": text},
    }

    logger.info("WA HTTP → Sending message to {}: {!r}", to_number, text)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code >= 400:
        logger.error(
            "WA HTTP error {}: {}",
            resp.status_code,
            resp.text,
        )
        # raise or just log; for now we'll raise to let ARQ retry if configured
        resp.raise_for_status()

    logger.success("WA HTTP → Message sent successfully to {}", to_number)
