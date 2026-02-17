# app/infrastructure/external/stt_sarvam.py
"""
Sarvam AI Speech-to-Text integration.

Requires environment variables:
    SARVAM_API_KEY   — your Sarvam API key
    SARVAM_STT_URL   — Sarvam STT endpoint URL
                        (e.g. https://api.sarvam.ai/speech-to-text)

Falls back gracefully if not configured — raises RuntimeError so the
caller (voice_handler.py) can return an appropriate error to the user.
"""

import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("stt_sarvam")

# Language code mapping (our codes → Sarvam codes)
_LANG_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
    "gu": "gu-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
}


async def transcribe_audio_sarvam(
    audio_bytes: bytes, language: str | None = None
) -> str:
    """Transcribe audio using Sarvam AI STT.

    Parameters
    ----------
    audio_bytes : bytes
        Raw audio data (OGG/WAV/MP3 from WhatsApp).
    language : str | None
        ISO-639-1 language hint (e.g. "hi", "en"). Optional.

    Returns
    -------
    str
        Transcribed text.

    Raises
    ------
    RuntimeError
        If Sarvam credentials are not configured.
    """
    if not settings.SARVAM_API_KEY or not settings.SARVAM_STT_URL:
        raise RuntimeError(
            "Sarvam STT not configured. "
            "Set SARVAM_API_KEY and SARVAM_STT_URL in your .env file."
        )

    sarvam_lang = _LANG_MAP.get(language or "", "hi-IN")

    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
    }

    # Sarvam expects multipart form data with the audio file
    files = {
        "file": ("audio.ogg", audio_bytes, "audio/ogg"),
    }
    form_data = {
        "language_code": sarvam_lang,
        "model": "saarika:v2",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            settings.SARVAM_STT_URL,
            headers=headers,
            files=files,
            data=form_data,
        )
        resp.raise_for_status()
        data = resp.json()

    # Sarvam API returns {"transcript": "..."} 
    transcript = data.get("transcript", "")
    if not transcript:
        logger.warning("Sarvam STT returned empty transcript: %s", data)
    return transcript
