# app/domain/services/health_check.py
"""
Comprehensive system health check service.

Probes all subsystems (DB, Redis, WhatsApp, OpenAI, OCR) and returns
a unified health report. Used by the dashboard route.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger("health_check")

# App start time — set once on import
_APP_START_TIME = datetime.now(timezone.utc)


@dataclass
class ComponentHealth:
    """Health status for a single system component."""
    name: str
    status: str  # "healthy", "degraded", "down", "not_configured"
    latency_ms: float = 0.0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Overall system health report."""
    status: str  # "healthy", "degraded", "down"
    timestamp: str = ""
    uptime_seconds: float = 0.0
    environment: str = ""
    version: str = "1.0.0"
    python_version: str = ""
    components: list[ComponentHealth] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "uptime_human": _format_uptime(self.uptime_seconds),
            "environment": self.environment,
            "version": self.version,
            "python_version": self.python_version,
            "components": [
                {
                    "name": c.name,
                    "status": c.status,
                    "latency_ms": round(c.latency_ms, 1),
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.components
            ],
            "stats": self.stats,
        }


def _format_uptime(seconds: float) -> str:
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Individual component probes
# ---------------------------------------------------------------------------

async def _check_database() -> ComponentHealth:
    """Probe PostgreSQL via SQLAlchemy async engine."""
    from app.core.db import engine
    from sqlalchemy import text

    start = time.monotonic()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.close()
        latency = (time.monotonic() - start) * 1000

        # Get connection pool stats
        pool = engine.pool
        details = {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }

        return ComponentHealth(
            name="PostgreSQL",
            status="healthy",
            latency_ms=latency,
            message="Connected",
            details=details,
        )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="PostgreSQL",
            status="down",
            latency_ms=latency,
            message=str(e)[:200],
        )


async def _check_redis() -> ComponentHealth:
    """Probe Redis connectivity."""
    if not settings.REDIS_URL:
        return ComponentHealth(
            name="Redis",
            status="not_configured",
            message="REDIS_URL not set",
        )

    import redis.asyncio as redis

    start = time.monotonic()
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            pong = await r.ping()
            latency = (time.monotonic() - start) * 1000

            # Get Redis info
            info = await r.info(section="memory")
            key_count = await r.dbsize()

            details = {
                "connected": bool(pong),
                "used_memory_human": info.get("used_memory_human", "N/A"),
                "total_keys": key_count,
            }

            # Count active sessions
            session_count = 0
            cursor = "0"
            while True:
                cursor, keys = await r.scan(
                    cursor=cursor, match="wa:session:*", count=100
                )
                session_count += len(keys)
                if cursor == "0" or cursor == 0:
                    break
            details["active_sessions"] = session_count

            return ComponentHealth(
                name="Redis",
                status="healthy",
                latency_ms=latency,
                message=f"Connected — {key_count} keys, {session_count} sessions",
                details=details,
            )
        finally:
            await r.aclose()
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="Redis",
            status="down",
            latency_ms=latency,
            message=str(e)[:200],
        )


async def _check_whatsapp_token() -> ComponentHealth:
    """Probe WhatsApp Cloud API token validity."""
    if not settings.WHATSAPP_ACCESS_TOKEN:
        return ComponentHealth(
            name="WhatsApp API",
            status="not_configured",
            message="WHATSAPP_ACCESS_TOKEN not set",
        )

    import httpx

    start = time.monotonic()
    try:
        url = "https://graph.facebook.com/v20.0/me"
        params = {"access_token": settings.WHATSAPP_ACCESS_TOKEN}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
        latency = (time.monotonic() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            return ComponentHealth(
                name="WhatsApp API",
                status="healthy",
                latency_ms=latency,
                message="Token valid",
                details={
                    "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID or "N/A",
                    "app_name": data.get("name", "N/A"),
                },
            )
        else:
            err = {}
            try:
                err = resp.json().get("error", {})
            except Exception:
                pass
            code = err.get("code", 0)
            msg = "Token expired" if code == 190 else "Token invalid"
            return ComponentHealth(
                name="WhatsApp API",
                status="down",
                latency_ms=latency,
                message=msg,
                details={"error_code": code},
            )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="WhatsApp API",
            status="down",
            latency_ms=latency,
            message=str(e)[:200],
        )


async def _check_openai() -> ComponentHealth:
    """Probe OpenAI API reachability."""
    if not settings.OPENAI_API_KEY:
        return ComponentHealth(
            name="OpenAI",
            status="not_configured",
            message="OPENAI_API_KEY not set",
        )

    import httpx

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            )
        latency = (time.monotonic() - start) * 1000

        if resp.status_code == 200:
            return ComponentHealth(
                name="OpenAI",
                status="healthy",
                latency_ms=latency,
                message=f"Connected (model: {settings.OPENAI_MODEL})",
                details={"model": settings.OPENAI_MODEL},
            )
        else:
            return ComponentHealth(
                name="OpenAI",
                status="down",
                latency_ms=latency,
                message=f"API returned {resp.status_code}",
            )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="OpenAI",
            status="down",
            latency_ms=latency,
            message=str(e)[:200],
        )


async def _check_ocr() -> ComponentHealth:
    """Check if Tesseract OCR is available."""
    import shutil

    start = time.monotonic()
    tesseract_path = shutil.which("tesseract")
    latency = (time.monotonic() - start) * 1000

    if tesseract_path:
        return ComponentHealth(
            name="Tesseract OCR",
            status="healthy",
            latency_ms=latency,
            message=f"Found at {tesseract_path}",
            details={"backend": settings.OCR_BACKEND, "path": tesseract_path},
        )
    else:
        return ComponentHealth(
            name="Tesseract OCR",
            status="down",
            latency_ms=latency,
            message="tesseract not found in PATH",
            details={"backend": settings.OCR_BACKEND},
        )


async def _check_whatsapp_queue() -> ComponentHealth:
    """Check WhatsApp message queue status."""
    from app.infrastructure.external.whatsapp_client import _outgoing_queue

    qsize = _outgoing_queue.qsize()
    status = "healthy" if qsize < 100 else "degraded"
    return ComponentHealth(
        name="Message Queue",
        status=status,
        latency_ms=0,
        message=f"{qsize} messages pending",
        details={"queue_size": qsize},
    )


async def _get_db_stats() -> dict[str, Any]:
    """Get database row counts for key tables."""
    from app.core.db import AsyncSessionLocal
    from sqlalchemy import text

    stats: dict[str, Any] = {}
    try:
        async with AsyncSessionLocal() as db:
            for table in [
                "users", "sessions", "invoices",
                "whatsapp_message_logs", "whatsapp_dead_letters",
                "ca_users", "business_clients",
            ]:
                try:
                    result = await db.execute(
                        text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                    )
                    stats[table] = result.scalar_one()
                except Exception:
                    stats[table] = "N/A"

            # Recent message stats (last 24h)
            try:
                result = await db.execute(text(
                    "SELECT status, COUNT(*) FROM whatsapp_message_logs "
                    "WHERE created_at >= NOW() - INTERVAL '24 hours' "
                    "GROUP BY status"
                ))
                msg_stats = {}
                for status, count in result.all():
                    msg_stats[status] = count
                stats["messages_24h"] = msg_stats
            except Exception:
                stats["messages_24h"] = {}

    except Exception as e:
        stats["error"] = str(e)[:200]

    return stats


# ---------------------------------------------------------------------------
# Main health check
# ---------------------------------------------------------------------------

async def run_health_check() -> SystemHealth:
    """
    Run all health probes concurrently and return a unified report.
    """
    now = datetime.now(timezone.utc)
    uptime = (now - _APP_START_TIME).total_seconds()

    # Run all probes concurrently
    results = await asyncio.gather(
        _check_database(),
        _check_redis(),
        _check_whatsapp_token(),
        _check_openai(),
        _check_ocr(),
        _check_whatsapp_queue(),
        return_exceptions=True,
    )

    components: list[ComponentHealth] = []
    for r in results:
        if isinstance(r, Exception):
            components.append(ComponentHealth(
                name="Unknown",
                status="down",
                message=str(r)[:200],
            ))
        else:
            components.append(r)

    # Get DB stats (separate from probes, slightly slower)
    try:
        db_stats = await _get_db_stats()
    except Exception:
        db_stats = {}

    # Determine overall status
    statuses = [c.status for c in components]
    if any(s == "down" for s in statuses):
        overall = "degraded"
    elif all(s in ("healthy", "not_configured") for s in statuses):
        overall = "healthy"
    else:
        overall = "degraded"

    return SystemHealth(
        status=overall,
        timestamp=now.isoformat(),
        uptime_seconds=uptime,
        environment=settings.ENV,
        version="1.0.0",
        python_version=platform.python_version(),
        components=components,
        stats=db_stats,
    )
