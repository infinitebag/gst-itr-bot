import os
import logging
from redis import Redis

logger = logging.getLogger("gst_itr_bot")


def whatsapp_sender_tick():
    """
    This is a placeholder job function for RQ.
    Put your actual job logic here (send pending whatsapp messages, etc.)
    """
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        logger.warning("REDIS_URL not set inside job.")
        return

    r = Redis.from_url(redis_url, decode_responses=True)
    r.ping()

    logger.info("[whatsapp_sender_tick] Job executed successfully.")