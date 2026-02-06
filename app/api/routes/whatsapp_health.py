import httpx
from fastapi import APIRouter, Query
from loguru import logger

from app.core.config import settings

router = APIRouter(prefix="/debug/whatsapp", tags=["WhatsApp Debug"])


@router.get("/token-health")
async def whatsapp_token_health(
    to: str = Query("", description="Optional test number like 91XXXXXXXXXX"),
):
    """
    Check if current WhatsApp token is valid by either:
    - hitting 'me' endpoint, or
    - sending a test message (if 'to' is provided).
    """

    if not settings.WHATSAPP_ACCESS_TOKEN:
        return {"ok": False, "reason": "No WHATSAPP_ACCESS_TOKEN set"}

    # Simple token debug by calling 'me' Graph endpoint
    me_url = "https://graph.facebook.com/v20.0/me"
    params = {"access_token": settings.WHATSAPP_ACCESS_TOKEN}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(me_url, params=params)

        if resp.status_code != 200:
            logger.error(
                "Token health check failed: {} - {}", resp.status_code, resp.text
            )
            try:
                err = resp.json().get("error", {})
            except Exception:
                err = {}
            code = err.get("code")
            subcode = err.get("error_subcode")
            if code == 190:
                msg = "Token expired"
            else:
                msg = "Token invalid or insufficient permissions"

            return {
                "ok": False,
                "reason": msg,
                "error": err,
            }

    result = {"ok": True, "reason": "Token valid (Graph /me check passed)"}

    # Optional: test send
    if to:
        from app.infrastructure.external.whatsapp_client import send_whatsapp_text

        await send_whatsapp_text(to, "Token health check from GST+ITR bot")
        result["test_send_to"] = to

    return result
