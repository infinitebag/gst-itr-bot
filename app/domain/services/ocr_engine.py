from typing import Protocol

from app.core.config import settings
from app.infrastructure.external.ocr_paddle import extract_text_from_image_bytes


class OCRBackend(Protocol):
    async def extract(
        self, image_bytes: bytes, session_lang: str | None = None
    ) -> str: ...


class TesseractOCRBackend:
    async def extract(self, image_bytes: bytes, session_lang: str | None = None) -> str:
        # sync helper wrapped in async
        return extract_text_from_image_bytes(image_bytes, session_lang=session_lang)


class GoogleVisionOCRBackend:
    def __init__(self):
        from google.cloud import vision  # type: ignore

        self.client = vision.ImageAnnotatorClient()

    async def extract(self, image_bytes: bytes, session_lang: str | None = None) -> str:
        from google.cloud import vision  # type: ignore

        image = vision.Image(content=image_bytes)
        response = self.client.document_text_detection(image=image)

        if response.error.message:
            print("Google Vision error:", response.error.message)
            return ""

        text = response.full_text_annotation.text or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)


_backend_singleton: OCRBackend | None = None


def get_ocr_backend() -> OCRBackend:
    global _backend_singleton
    if _backend_singleton is not None:
        return _backend_singleton

    backend = settings.OCR_BACKEND.lower()
    if backend == "google":
        _backend_singleton = GoogleVisionOCRBackend()
    else:
        _backend_singleton = TesseractOCRBackend()

    return _backend_singleton
