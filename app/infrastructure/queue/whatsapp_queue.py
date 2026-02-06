# app/infrastructure/queue/whatsapp_queue.py

from arq.connections import ArqRedis, RedisSettings, create_pool
from loguru import logger

from app.core.config import settings

_redis_pool: ArqRedis | None = None


async def get_redis_pool() -> ArqRedis:
    """
    Creates (once) and returns an Arq Redis pool.
    """
    global _redis_pool
    if _redis_pool is None:
        logger.info("Creating ARQ Redis pool: {}", settings.REDIS_URL)
        _redis_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        logger.success("ARQ Redis pool ready")

    return _redis_pool


async def enqueue_whatsapp_message(to_number: str, text: str) -> None:
    """
    Enqueue a background job to send a WhatsApp message.
    Runs quickly inside FastAPI; heavy lifting happens in worker.
    """
    redis = await get_redis_pool()

    try:
        await redis.enqueue_job(
            "send_whatsapp_job",  # ← job name in WorkerSettings.functions
            to_number,
            text,
        )
        logger.info("ARQ → Enqueued WA message to {}", to_number)

    except Exception as e:
        logger.exception("ARQ enqueue failed for {}: {}", to_number, e)
