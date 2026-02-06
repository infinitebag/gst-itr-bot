from __future__ import annotations
from typing import Optional, Dict, Any
import hashlib
from sqlalchemy import text
from app.core.db import engine  # your async SQLAlchemy engine

def _hash_wa(wa_id: str) -> str:
    return hashlib.sha256(wa_id.encode("utf-8")).hexdigest()[:24]

async def track_event(wa_id: str, event_name: str, state: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> None:
    wa = _hash_wa(wa_id)
    meta = meta or {}
    q = text(
        "INSERT INTO analytics_events (wa_id, event_name, state, meta) VALUES (:wa_id, :event_name, :state, :meta::jsonb)"
    )
    async with engine.begin() as conn:
        await conn.execute(q, {"wa_id": wa, "event_name": event_name, "state": state, "meta": str(meta).replace("'", '"')})