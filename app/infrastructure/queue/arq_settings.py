# app/infrastructure/queue/arq_settings.py

from arq.connections import RedisSettings
from loguru import logger

from app.core.config import settings
from app.infrastructure.queue.whatsapp_jobs import send_whatsapp_job


class WorkerSettings:
    """
    Used by:
        arq app.infrastructure.queue.arq_settings.WorkerSettings
    """

    # Redis connection
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    # Jobs this worker can execute
    functions = [send_whatsapp_job]

    # Optional tuning
    max_jobs = 100
    allow_abort_jobs = True

    @staticmethod
    async def on_startup(ctx):
        """
        Called once when the worker starts.
        `ctx` is a dict-like object you can use to store shared resources.
        """
        logger.info("ARQ worker starting up, Redis DSN={}", settings.REDIS_URL)

    @staticmethod
    async def on_shutdown(ctx):
        """
        Called once when the worker is shutting down.
        """
        logger.info("ARQ worker shutting down")
