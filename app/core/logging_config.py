# app/core/logging_config.py

import logging
import sys

from loguru import logger


def setup_logging() -> None:
    """
    Configure loguru as the main logger with colored, structured logs.
    Also redirect stdlib logging (uvicorn, sqlalchemy, etc.) to loguru.
    """
    # Remove default loguru handler
    logger.remove()

    # Add our handler: colored, with time + level + module + message
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level="INFO",
        colorize=True,
        backtrace=False,
        diagnose=False,
    )

    # Redirect stdlib logging to loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # Get logger for this record
            level = record.levelname
            try:
                level = logger.level(level).name
            except Exception:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)
    logging.getLogger("uvicorn").handlers = [InterceptHandler()]
    logging.getLogger("uvicorn.error").handlers = [InterceptHandler()]
    logging.getLogger("uvicorn.access").handlers = [InterceptHandler()]
    # Quieten noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
