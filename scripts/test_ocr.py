# scripts/test_ocr.py

import asyncio
from pathlib import Path

from app.infrastructure.ocr.factory import get_ocr_backend


async def main():
    backend = get_ocr_backend()

    # 1) Point this to your sample PDF or image
    path = Path("sample_gst_invoice.pdf")  # or "tests/data/invoice.jpg"
    data = path.read_bytes()

    text = await backend.extract(
        data,
        session_lang="en",
        mime_type="application/pdf",  # change to "image/jpeg" if testing an image
    )

    print("---- OCR OUTPUT (first 2000 chars) ----")
    print(text[:2000])


if __name__ == "__main__":
    asyncio.run(main())