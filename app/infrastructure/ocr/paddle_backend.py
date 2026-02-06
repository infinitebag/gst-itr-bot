from __future__ import annotations
from typing import Optional
from paddleocr import PaddleOCR

# Keep a singleton in-process (fast)
_OCR = None

def get_ocr(lang: str = "en") -> PaddleOCR:
    global _OCR
    if _OCR is None:
        # lang: "en" or "hi" etc (Paddle uses codes like "en", "hi")
        _OCR = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
    return _OCR

async def extract_text_from_image_bytes(image_bytes: bytes, lang: str = "en") -> str:
    import numpy as np
    import cv2

    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        return ""

    ocr = get_ocr(lang=lang)
    results = ocr.ocr(img, cls=True) or []
    lines = []
    for block in results:
        for item in block:
            text = item[1][0]
            if text:
                lines.append(text)
    return "\n".join(lines)