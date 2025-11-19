import httpx
from app.core.config import settings

WA_BASE = "https://graph.facebook.com/v18.0"

async def send_whatsapp_text(to: str, text: str):
    url = f"{WA_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": { "body": text }
    }
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)