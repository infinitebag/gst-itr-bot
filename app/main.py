# app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.db import db_ping
from app.api.routes import api_router

logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Application startup")
    try:
        await db_ping()
        logger.info("✅ Database connected")
    except Exception:
        logger.exception("❌ Database connection failed")
        raise
    yield
    logger.info("🛑 Application shutdown")

app = FastAPI(lifespan=lifespan)
app.include_router(api_router)