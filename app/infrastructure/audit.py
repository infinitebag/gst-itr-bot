# app/infrastructure/audit.py
"""
Simple audit logger for admin and CA dashboard actions.

Logs who did what, when, and from where. In production you'd persist these
to a DB table — for now we use structured logging that can be ingested
by any log aggregator (ELK, CloudWatch, Datadog, etc.).
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("audit")


def log_admin_action(
    action: str,
    *,
    admin_ip: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Log an admin action (dead-letter replay, invoice seed, etc.)."""
    logger.info(
        "ADMIN_ACTION action=%s ip=%s time=%s details=%s",
        action,
        admin_ip,
        datetime.now(timezone.utc).isoformat(),
        details or {},
    )


def log_ca_action(
    action: str,
    *,
    ca_id: int | None = None,
    ca_email: str = "",
    client_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log a CA dashboard action (client CRUD, PDF export, etc.)."""
    logger.info(
        "CA_ACTION action=%s ca_id=%s ca_email=%s client_id=%s time=%s details=%s",
        action,
        ca_id,
        ca_email,
        client_id,
        datetime.now(timezone.utc).isoformat(),
        details or {},
    )
