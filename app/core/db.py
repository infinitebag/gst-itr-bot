from __future__ import annotations

from typing import Any, AsyncGenerator
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _sanitize_asyncpg_url(url: str) -> str:
    """
    asyncpg does not accept 'sslmode' as a connect kwarg.
    Strip it from the URL query string to avoid TypeError.
    """
    parts = urlsplit(url)
    q = [
        (k, v)
        for (k, v) in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() != "sslmode"
    ]
    new_query = urlencode(q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _needs_ssl(url: str) -> bool:
    """
    Auto-detect whether SSL is required for the database connection.

    Returns True when:
    - ENV is production/staging, OR
    - DATABASE_URL points to a known cloud provider (Neon, Supabase, RDS, etc.)

    Returns False for local dev (localhost, 127.0.0.1, Docker service name).
    """
    # Cloud provider hostnames that always require SSL
    _CLOUD_HOSTS = ("neon.tech", "supabase.co", "supabase.com", "aivencloud.com",
                    "rds.amazonaws.com", "render.com", "railway.app", "elephantsql.com")

    host = urlsplit(url).hostname or ""

    # Explicit production environment
    if settings.ENV in ("production", "staging", "prod"):
        return True

    # Known cloud database providers
    if any(cloud in host for cloud in _CLOUD_HOSTS):
        return True

    # Local development (Docker, localhost)
    if host in ("localhost", "127.0.0.1", "db", "postgres", "0.0.0.0"):
        return False

    # Default: no SSL for unrecognised hosts in dev
    return False


# ------------------------------------------------------------------------------
# DATABASE SETTINGS
# ------------------------------------------------------------------------------
DATABASE_URL = _sanitize_asyncpg_url(settings.DATABASE_URL)
_USE_SSL = _needs_ssl(settings.DATABASE_URL)

# ------------------------------------------------------------------------------
# DATABASE ENGINE
# ------------------------------------------------------------------------------
_connect_args: dict = {}
if _USE_SSL:
    import ssl as _ssl

    # Create a proper SSL context for cloud database providers.
    # Uses system CA certificates for verification (secure default).
    # If your cloud provider requires a custom CA, point to it:
    #   _ctx.load_verify_locations("/path/to/ca-certificate.crt")
    _ctx = _ssl.create_default_context()
    _connect_args["ssl"] = _ctx
else:
    _connect_args["ssl"] = False

engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    future=True,
    pool_size=20,
    max_overflow=40,
    pool_timeout=30,
    pool_recycle=1800,
    connect_args=_connect_args,
)

# ------------------------------------------------------------------------------
# SESSION FACTORY
# ------------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ------------------------------------------------------------------------------
# DEPENDENCIES / HEALTH
# ------------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession | Any, Any]:
    async with AsyncSessionLocal() as session:
        yield session


async def db_ping() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_db() -> None:
    await engine.dispose()
