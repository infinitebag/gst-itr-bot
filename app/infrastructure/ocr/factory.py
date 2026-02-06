from __future__ import annotations

from app.infrastructure.ocr.paddle_backend import extract_text_from_image_bytes
from app.infrastructure.ocr.pdf_backend import pdf_bytes_to_first_page_png

async def extract_text_from_invoice_bytes(file_bytes: bytes, mime_type: str, lang: str = "en") -> str:
    mime_type = (mime_type or "").lower()

    if "pdf" in mime_type:
        img = await pdf_bytes_to_first_page_png(file_bytes)
        if not img:
            return ""
        return await extract_text_from_image_bytes(img, lang=lang)

    # image/*
    return await extract_text_from_image_bytes(file_bytes, lang=lang)