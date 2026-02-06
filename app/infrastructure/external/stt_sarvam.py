import httpx

from app.core.config import settings


async def transcribe_audio_sarvam(
    audio_bytes: bytes, language: str | None = None
) -> str:
    """
    Generic Sarvam STT wrapper.
    You must set SARVAM_STT_URL + SARVAM_API_KEY in .env.local
    The exact payload depends on their latest docs; treat this as a template.
    """
    if not settings.SARVAM_API_KEY or not settings.SARVAM_STT_URL:
        raise RuntimeError("Sarvam STT not configured")

    headers = {
        "Authorization": f"Bearer {settings.SARVAM_API_KEY}",
        "Content-Type": "application/octet-stream",
    }

    # Some STT APIs take params via query or JSON; adapt as per Sarvam's docs
    params = {}
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            settings.SARVAM_STT_URL,
            headers=headers,
            params=params,
            content=audio_bytes,
        )
        resp.raise_for_status()
        data = resp.json()
        # Adjust key according to actual API response
        return data.get("text") or data.get("transcript") or ""
