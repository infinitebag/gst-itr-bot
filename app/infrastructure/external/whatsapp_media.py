# app/infrastructure/external/whatsapp_media.py

import os
from typing import Optional

import httpx


GRAPH_BASE = os.getenv("WHATSAPP_GRAPH_BASE", "https://graph.facebook.com")
GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v20.0")


def _wa_token() -> str:
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("WHATSAPP_ACCESS_TOKEN is not set")
    return token


async def get_media_url(media_id: str) -> str:
    """
    1) GET /{media_id} -> returns {"url": "..."}
    """
    url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{media_id}"
    headers = {"Authorization": f"Bearer {_wa_token()}"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        media_url = data.get("url")
        if not media_url:
            raise RuntimeError(f"WhatsApp media url not found for media_id={media_id}")
        return media_url


async def download_media(media_url: str) -> bytes:
    """
    2) GET bytes from returned media URL (still requires Authorization header)
    """
    headers = {"Authorization": f"Bearer {_wa_token()}"}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(media_url, headers=headers)
        r.raise_for_status()
        return r.content


async def whatsapp_send_text(
    to_wa_id: str,
    text: str,
    phone_number_id: Optional[str] = None,
) -> None:
    """
    Send a text message via:
    POST /{PHONE_NUMBER_ID}/messages
    """
    phone_number_id = phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    if not phone_number_id:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID is not set")

    url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {_wa_token()}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        # don't hard-fail webhook if send fails; log upstream in caller if needed
        r.raise_for_status()