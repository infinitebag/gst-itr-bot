# app/infrastructure/queue/tasks.py
import dramatiq
from loguru import logger

from .broker import broker  # noqa: F401  - ensures broker is set


@dramatiq.actor
def send_whatsapp_async(to_number: str, text: str):
    logger.info("Async sending WhatsApp message to {}: {}", to_number, text)
    # Here call your existing send_whatsapp_text logic (or a refactored version)
