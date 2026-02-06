from io import BytesIO

import pytesseract
from PIL import Image

# Map your bot language codes -> Tesseract language packs
LANG_MAP = {
    "en": "eng",
    "hi": "eng+hin",  # English + Hindi
    "te": "eng+tel",  # English + Telugu
    # extend later: 'tam' for Tamil, 'guj' for Gujarati etc
}


def extract_text_from_image_bytes(
    image_bytes: bytes, session_lang: str | None = None
) -> str:
    """
    Run OCR on an image (bytes) using Tesseract and return extracted text.
    session_lang: e.g. 'en', 'hi', 'te'. If None -> English only.
    """

    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception as e:
        print("Tesseract OCR: cannot open image:", e)
        return ""

    tess_lang = LANG_MAP.get(session_lang or "en", "eng")

    try:
        text = pytesseract.image_to_string(img, lang=tess_lang)
    except Exception as e:
        print("Tesseract OCR error:", e)
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
