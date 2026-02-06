from pdf2image import convert_from_bytes
from io import BytesIO

async def pdf_bytes_to_first_page_png(pdf_bytes: bytes) -> bytes:
    pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1)
    if not pages:
        return b""
    buf = BytesIO()
    pages[0].save(buf, format="PNG")
    return buf.getvalue()