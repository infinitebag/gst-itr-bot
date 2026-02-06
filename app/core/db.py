from __future__ import annotations

from typing import Any, AsyncGenerator, Optional
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config.settings import settings

Base = declarative_base()


def _get_setting(*names: str, default: Any = None) -> Any:
    """
    Settings compatibility helper.
    Tries multiple attribute names (e.g. database_url / DATABASE_URL).
    """
    for n in names:
        if hasattr(settings, n):
            return getattr(settings, n)
    return default


def _sanitize_asyncpg_url(url: str) -> str:
    """
    asyncpg DOES NOT accept 'sslmode' kwarg, and SQLAlchemy will forward URL query
    params as connect args. If your URL has ?sslmode=disable it becomes:
      TypeError: connect() got an unexpected keyword argument 'sslmode'
    So we strip sslmode from the URL query.
    """
    parts = urlsplit(url)
    q = [(k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "sslmode"]
    new_query = urlencode(q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


# ------------------------------------------------------------------------------
# DATABASE SETTINGS
# ------------------------------------------------------------------------------
DATABASE_URL: Optional[str] = _get_setting("database_url", "DATABASE_URL")
DEBUG: bool = bool(_get_setting("debug", "DEBUG", default=False))

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured (tried settings.database_url and settings.DATABASE_URL).")

DATABASE_URL = _sanitize_asyncpg_url(DATABASE_URL)

# ------------------------------------------------------------------------------
# DATABASE ENGINE
# ------------------------------------------------------------------------------
# Local docker Postgres typically has NO SSL; forcing ssl=False avoids:
#   ConnectionError: PostgreSQL server ... rejected SSL upgrade
engine = create_async_engine(
    DATABASE_URL,
    echo=DEBUG,
    pool_pre_ping=True,
    future=True,
    connect_args={
        "ssl": False,  # critical for local docker Postgres
    },
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
    """
    Lightweight DB connectivity check.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_db() -> None:
    """
    Graceful shutdown helper.
    """
    await engine.dispose()