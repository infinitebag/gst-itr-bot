import io
import logging
from typing import Optional

import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}


async def extract_text_from_invoice_bytes(
    file_bytes: bytes,
    mime_type: Optional[str] = None,
) -> str:
    """
    Extract text from invoice bytes using Tesseract OCR.

    Supports:
    - PDF invoices
    - Image invoices (jpg/png/webp)

    Returns extracted text (may be empty string).
    """

    if not file_bytes:
        logger.warning("Empty file bytes passed to OCR")
        return ""

    try:
        # ---------- PDF ----------
        if mime_type == "application/pdf":
            return _extract_from_pdf(file_bytes)

        # ---------- IMAGE ----------
        if mime_type in SUPPORTED_IMAGE_TYPES or mime_type is None:
            return _extract_from_image(file_bytes)

        logger.warning(f"Unsupported mime type for OCR: {mime_type}")
        return ""

    except Exception as e:
        logger.exception("OCR extraction failed")
        return ""


# ---------------- INTERNAL HELPERS ---------------- #

def _extract_from_pdf(file_bytes: bytes) -> str:
    """
    Convert PDF to images and OCR each page.
    """
    text_chunks = []

    images = convert_from_bytes(
        file_bytes,
        dpi=300,
        fmt="jpeg",
    )

    for idx, image in enumerate(images):
        page_text = pytesseract.image_to_string(image)
        if page_text:
            text_chunks.append(page_text)

    return "\n".join(text_chunks).strip()


def _extract_from_image(file_bytes: bytes) -> str:
    """
    OCR directly from image bytes.
    """
    image = Image.open(io.BytesIO(file_bytes))
    text = pytesseract.image_to_string(image)
    return text.strip() if text else ""