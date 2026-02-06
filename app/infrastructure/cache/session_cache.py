import json
from typing import Any, Dict
import redis.asyncio as redis


DEFAULT_SESSION = {
    "state": "MAIN_MENU",
    "lang": "en",
    "stack": [],
    "data": {},
}


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
            return DEFAULT_SESSION.copy()
        try:
            return json.loads(raw)
        except Exception:
            return DEFAULT_SESSION.copy()

    async def save_session(
        self,
        wa_id: str,
        session: Dict[str, Any],
        ttl_seconds: int = 60 * 60 * 24,
    ) -> None:
        await self._r.set(
            self._key(wa_id),
            json.dumps(session),
            ex=ttl_seconds,
        )

    async def clear_session(self, wa_id: str) -> None:
        await self._r.delete(self._key(wa_id))


# 🔁 BACKWARD-COMPATIBLE ALIASES (THIS FIXES YOUR ERRORS)
async def get_cached_session(cache: SessionCache, wa_id: str):
    return await cache.get_session(wa_id)


async def cache_session(cache: SessionCache, wa_id: str, session: Dict[str, Any]):
    await cache.save_session(wa_id, session)


async def invalidate_session_cache(cache: SessionCache, wa_id: str):
    await cache.clear_session(wa_id)