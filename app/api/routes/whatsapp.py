from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.db import get_db
from app.domain.services.conversation_service import handle_incoming_message

router = APIRouter()

@router.get("/webhook", response_class=PlainTextResponse)
async def verify(hub_mode: str=None, hub_challenge: str=None, hub_verify_token: str=None):
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return hub_challenge
    return "Verification failed"

@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    entry = (body.get("entry") or [])[0]
    changes = (entry.get("changes") or [])[0]
    value = changes.get("value") or {}
    messages = value.get("messages") or []

    if messages:
        await handle_incoming_message(db, value, messages[0])

    return {"status": "ok"}