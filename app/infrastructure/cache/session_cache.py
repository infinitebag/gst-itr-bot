import json
import time
from typing import Any, Dict

import redis.asyncio as redis

# ---------------------------------------------------------------------------
# Session version & TTL constants
# ---------------------------------------------------------------------------
SESSION_VERSION = 2
SESSION_TTL_SECONDS = 14 * 24 * 60 * 60        # 14 days hard expiry
SOFT_EXPIRY_SECONDS = 30 * 60                   # 30 min idle → resume prompt
SENSITIVE_TIMEOUT_SECONDS = 10 * 60             # 10 min for confirm screens


def _default_session() -> Dict[str, Any]:
    """Return a fresh default session dict (avoids shared mutable state)."""
    return {
        "version": SESSION_VERSION,
        "state": "CHOOSE_LANG",
        "lang": "en",
        "stack": [],
        "data": {},
        "last_active_ts": time.time(),
    }


def _migrate_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate a v1 session to v2 in-place and return it.

    * Adds ``version``, ``last_active_ts`` if missing.
    * Maps deprecated states to their new equivalents (identity for now).
    """
    if session.get("version", 1) >= SESSION_VERSION:
        return session
    session["version"] = SESSION_VERSION
    session.setdefault("last_active_ts", time.time())
    # Future: remap deprecated state strings here, e.g.
    # state_map = {"WAIT_GSTIN": "GST_START_GSTIN", ...}
    # session["state"] = state_map.get(session["state"], session["state"])
    return session


def is_soft_expired(session: Dict[str, Any]) -> bool:
    """Return True if session has been idle longer than SOFT_EXPIRY_SECONDS."""
    last_ts = session.get("last_active_ts", 0)
    return (time.time() - last_ts) > SOFT_EXPIRY_SECONDS


def is_sensitive_expired(session: Dict[str, Any]) -> bool:
    """Return True if session has been idle longer than SENSITIVE_TIMEOUT_SECONDS."""
    last_ts = session.get("last_active_ts", 0)
    return (time.time() - last_ts) > SENSITIVE_TIMEOUT_SECONDS


def touch_session(session: Dict[str, Any]) -> None:
    """Update the last_active_ts to current time (call on every inbound msg)."""
    session["last_active_ts"] = time.time()


class SessionCache:
    def __init__(self, redis_url: str):
        if not redis_url:
            raise RuntimeError("REDIS_URL is not set")
        self._r = redis.from_url(redis_url, decode_responses=True)

    def _key(self, wa_id: str) -> str:
        return f"wa:session:{wa_id}"

    async def get_session(self, wa_id: str) -> Dict[str, Any]:
        raw = await self._r.get(self._key(wa_id))
        if not raw:
            return _default_session()
        try:
            session = json.loads(raw)
            return _migrate_session(session)
        except Exception:
            return _default_session()

    async def save_session(
        self,
        wa_id: str,
        session: Dict[str, Any],
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> None:
        await self._r.set(
            self._key(wa_id),
            json.dumps(session),
            ex=ttl_seconds,
        )

    async def clear_session(self, wa_id: str) -> None:
        await self._r.delete(self._key(wa_id))


# ---------------------------------------------------------------------------
# Module-level aliases used by conversation_service and session_repository.
# These exist for backward compatibility — prefer using SessionCache directly.
# ---------------------------------------------------------------------------
async def get_cached_session(cache_or_id, wa_id: str | None = None) -> Dict[str, Any]:
    if isinstance(cache_or_id, SessionCache):
        return await cache_or_id.get_session(wa_id)  # type: ignore[arg-type]
    return _default_session()


async def cache_session(
    cache_or_id, wa_id_or_data=None, data: Dict[str, Any] | None = None
) -> None:
    if isinstance(cache_or_id, SessionCache):
        await cache_or_id.save_session(wa_id_or_data, data or {})


async def invalidate_session_cache(cache_or_id, wa_id: str | None = None) -> None:
    if isinstance(cache_or_id, SessionCache):
        await cache_or_id.clear_session(wa_id)  # type: ignore[arg-type]
