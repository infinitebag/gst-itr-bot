# app/infrastructure/cache/redis_client.py

import redis.asyncio as redis

from app.core.config import settings

redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return redis_client
