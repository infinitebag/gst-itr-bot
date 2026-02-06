# scripts/check_whatsapp_token.py

import asyncio
import os
import sys

# ensure app is importable
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from loguru import logger
from app.core.logging_config import setup_logging
from app.core.config import settings
import httpx


async def main():
    setup_logging()
    if not settings.WHATSAPP_ACCESS_TOKEN:
        logger.error("No WHATSAPP_ACCESS_TOKEN configured")
        return

    me_url = "https://graph.facebook.com/v20.0/me"
    params = {"access_token": settings.WHATSAPP_ACCESS_TOKEN}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(me_url, params=params)
        if resp.status_code != 200:
            logger.error("Token check failed: {} - {}", resp.status_code, resp.text)
            try:
                err = resp.json().get("error", {})
            except Exception:
                err = {}
            code = err.get("code")
            if code == 190:
                logger.critical(
                    "WhatsApp token EXPIRED (code=190). Generate a new token and update .env.local"
                )
            else:
                logger.error("Token invalid: {}", err)
        else:
            logger.success("WhatsApp token OK")


if __name__ == "__main__":
    asyncio.run(main())