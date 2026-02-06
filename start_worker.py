# start_worker.py
"""
Simple Dramatiq worker runner for Docker.
Make sure your Dramatiq broker is initialized in app.infrastructure.queue.broker
and actors are imported in app.infrastructure.queue.tasks.
"""

import dramatiq
from loguru import logger

# Import your task modules so Dramatiq can discover actors
# Adjust these imports to your actual paths
try:
    from app.infrastructure.queue import tasks  # noqa: F401
except Exception as e:
    logger.error("Error importing Dramatiq tasks: {}", e)

if __name__ == "__main__":
    logger.info("Starting Dramatiq worker...")
    dramatiq.cli.main()