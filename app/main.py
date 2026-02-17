# app/main.py
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings, validate_secrets
from app.core.db import db_ping
from app.api.routes import api_router
from app.infrastructure.external.whatsapp_client import start_whatsapp_sender_worker
from app.domain.services.deadline_scheduler import start_deadline_reminder_loop

logger = logging.getLogger("app.main")

# Resolve static directory relative to this file
_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup  (ENV=%s)", settings.ENV)

    # Validate secrets early — will raise in prod if defaults still in use
    validate_secrets()

    try:
        await db_ping()
        logger.info("Database connected")
    except Exception:
        logger.exception("Database connection failed")
        raise

    # Start background workers
    sender_task = asyncio.create_task(start_whatsapp_sender_worker())
    reminder_task = asyncio.create_task(start_deadline_reminder_loop())
    logger.info("Background workers started (WhatsApp sender + deadline reminders)")

    yield

    # Cancel background tasks on shutdown
    sender_task.cancel()
    reminder_task.cancel()
    try:
        await sender_task
    except asyncio.CancelledError:
        pass
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    logger.info("Application shutdown")


app = FastAPI(
    title="GST + ITR Tax Bot API",
    description="REST API for Indian GST and ITR tax compliance — WhatsApp bot, mobile and web integration.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow admin dashboards to be accessed from known origins.
# In dev mode we permit all origins for convenience; in production restrict
# to your actual domain(s).
# ---------------------------------------------------------------------------
_CORS_ORIGINS: list[str] = (
    ["*"]
    if settings.ENV in ("dev", "development", "test")
    else [
        f"http://localhost:{settings.PORT}",
        f"https://localhost:{settings.PORT}",
        # Add your production domain(s) here, e.g.:
        # "https://yourdomain.com",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
app.include_router(api_router)

# ---------------------------------------------------------------------------
# v1 REST API — mobile / web clients
# ---------------------------------------------------------------------------
from app.api.v1 import v1_router  # noqa: E402

app.include_router(v1_router)
