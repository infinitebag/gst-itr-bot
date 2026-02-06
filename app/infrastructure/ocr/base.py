# app/infrastructure/ocr/base.py

from __future__ import annotations

from abc import ABC, abstractmethod


class OcrBackend(ABC):
    """Abstract OCR backend interface."""

    @abstractmethod
    async def extract(
        self,
        data: bytes,
        session_lang: str | None = None,
        mime_type: str | None = None,
    ) -> str:
        """
        Extract text from invoice bytes.

        :param data: raw file bytes (image or PDF)
        :param session_lang: 'en', 'hi', 'te', etc. (optional)
        :param mime_type: e.g. 'image/jpeg', 'application/pdf' (optional)
        """
        raise NotImplementedError
