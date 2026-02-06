import httpx

from app.core.config import settings

AISENSY_BASE_URL = "https://backend.aisensy.com/"


async def send_whatsapp_text(to: str, text: str) -> None:
    """
    For now: send via AiSensy free trial.
    Later: you can switch implementation to WhatsApp Cloud API.

    `to` must be like "91XXXXXXXXXX"
    """
    if not settings.AISENSY_API_KEY:
        print("AiSensy API key not set; cannot send WhatsApp message.")
        return

    url = f"{AISENSY_BASE_URL}campaign/t1/api"
    payload = {
        "apiKey": settings.AISENSY_API_KEY,
        "campaignName": "AUTO-MESSAGES",
        "destination": to,
        "userName": "BOT",
        # For simple free messages, AiSensy often accepts plain text in templateParams
        "templateParams": [text],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            print("AiSensy send error:", resp.status_code, resp.text)
