# app/domain/services/voice_handler.py

import logging
from dataclasses import dataclass

from app.infrastructure.external.whatsapp_media import get_media_url, download_media
from app.infrastructure.external.stt_sarvam import transcribe_audio_sarvam
from app.infrastructure.external.translation_bhashini import translate_with_bhashini

logger = logging.getLogger("voice_handler")


@dataclass
class VoiceResult:
    transcribed_text: str = ""
    detected_lang: str | None = None
    translated_text: str | None = None
    error: str | None = None


async def process_voice_message(
    media_id: str,
    session_lang: str,
) -> VoiceResult:
    """
    Complete voice message processing pipeline:
    1. Download audio from WhatsApp Media API
    2. Transcribe via Sarvam STT
    3. Optionally translate via Bhashini (if configured)
    """
    try:
        # Step 1: Download audio
        media_url = await get_media_url(media_id)
        audio_bytes = await download_media(media_url)

        if not audio_bytes:
            return VoiceResult(error="download_failed")

        # Step 2: Transcribe via Sarvam STT
        try:
            transcribed = await transcribe_audio_sarvam(
                audio_bytes, language=session_lang
            )
        except RuntimeError:
            # Sarvam not configured
            return VoiceResult(error="stt_not_configured")

        if not transcribed or not transcribed.strip():
            return VoiceResult(error="transcription_empty")

        # Step 3: Optionally translate to English for NLP processing
        # GPT-4o handles multilingual well, so translation is optional
        translated = None
        if session_lang and session_lang != "en":
            try:
                translated = await translate_with_bhashini(
                    transcribed,
                    source_lang=session_lang,
                    target_lang="en",
                )
                # If Bhashini returns the same text, it wasn't configured
                if translated == transcribed:
                    translated = None
            except Exception:
                logger.debug("Bhashini translation unavailable, using raw transcription")

        return VoiceResult(
            transcribed_text=transcribed.strip(),
            detected_lang=session_lang,
            translated_text=translated,
        )

    except Exception:
        logger.exception("Voice message processing failed")
        return VoiceResult(error="processing_failed")
