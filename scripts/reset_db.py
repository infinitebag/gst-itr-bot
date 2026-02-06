# scripts/reset_db.py

import asyncio
import os
import sys
from loguru import logger

# ✅ Ensure project root (the folder containing 'app') is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from app.core.db import engine  # uses your Neon engine with SSL
from app.infrastructure.db.base import Base  # your declarative Base


async def reset_db():
    logger.info("Connecting to Neon DB and resetting schema (drop_all + create_all)...")

    async with engine.begin() as conn:
        logger.info("Dropping all tables...")
        await conn.run_sync(Base.metadata.drop_all)

        logger.info("Creating all tables from current models...")
        await conn.run_sync(Base.metadata.create_all)

    logger.success("✅ DB reset complete: all tables dropped and recreated on Neon.")


if __name__ == "__main__":
    asyncio.run(reset_db())