import httpx

from app.core.config import settings


async def translate_with_bhashini(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> str:
    """
    Generic NMT wrapper.
    The exact payload depends on the Bhashini/ULCA pipeline you choose.
    Here we keep it generic using env-configured URL.
    """
    if not settings.BHASHINI_API_KEY or not settings.BHASHINI_TRANSLATION_URL:
        # If not configured, just return original text
        return text

    headers = {
        "Authorization": f"Bearer {settings.BHASHINI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "source_lang": source_lang,
        "target_lang": target_lang,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            settings.BHASHINI_TRANSLATION_URL, json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("translated_text", text)
