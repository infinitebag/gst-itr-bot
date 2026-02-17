# app/domain/services/audit_service.py
"""
Audit trail service for tracking data access and operations.

Logs every access to client data by CAs, admins, or system operations
for compliance and security monitoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger("audit_service")

# In-memory audit log for quick access (also logged to structured logging)
_audit_buffer: list[dict] = []
_MAX_BUFFER_SIZE = 10000


@dataclass
class AuditEntry:
    """A single audit log entry."""
    timestamp: str
    actor_type: str      # "ca" | "admin" | "system" | "user"
    actor_id: str        # CA email, admin token hash, system process name, WhatsApp ID
    action: str          # "view" | "edit" | "delete" | "export" | "file" | "access"
    resource_type: str   # "client" | "invoice" | "filing" | "notice" | "refund"
    resource_id: str     # ID of the accessed resource
    client_gstin: str | None = None
    details: str | None = None
    ip_address: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "client_gstin": self.client_gstin,
            "details": self.details,
            "ip_address": self.ip_address,
        }


def log_access(
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    client_gstin: str | None = None,
    details: str | None = None,
    ip_address: str | None = None,
) -> AuditEntry:
    """Log a data access event.

    This is synchronous and non-blocking -- writes to structured log
    and in-memory buffer. For production, integrate with a DB table
    or external audit service.
    """
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        client_gstin=client_gstin,
        details=details,
        ip_address=ip_address,
    )

    # Structured logging
    logger.info(
        "AUDIT: %s %s %s %s/%s gstin=%s",
        entry.actor_type,
        entry.actor_id,
        entry.action,
        entry.resource_type,
        entry.resource_id,
        entry.client_gstin or "-",
    )

    # Buffer for API queries
    _audit_buffer.append(entry.to_dict())
    if len(_audit_buffer) > _MAX_BUFFER_SIZE:
        _audit_buffer.pop(0)

    return entry


def get_recent_audit_entries(
    limit: int = 50,
    actor_type: str | None = None,
    client_gstin: str | None = None,
    action: str | None = None,
) -> list[dict]:
    """Query recent audit entries from in-memory buffer.

    For production, this should query a database table.
    """
    results = _audit_buffer.copy()

    if actor_type:
        results = [e for e in results if e["actor_type"] == actor_type]
    if client_gstin:
        results = [e for e in results if e["client_gstin"] == client_gstin]
    if action:
        results = [e for e in results if e["action"] == action]

    # Return most recent first
    results.reverse()
    return results[:limit]


def get_access_summary(client_gstin: str) -> dict:
    """Get access summary for a specific client GSTIN.

    Returns who accessed this client's data and when.
    """
    entries = [e for e in _audit_buffer if e["client_gstin"] == client_gstin]

    actors = {}
    for e in entries:
        key = f"{e['actor_type']}:{e['actor_id']}"
        if key not in actors:
            actors[key] = {"first_access": e["timestamp"], "last_access": e["timestamp"], "count": 0}
        actors[key]["last_access"] = e["timestamp"]
        actors[key]["count"] += 1

    return {
        "client_gstin": client_gstin,
        "total_accesses": len(entries),
        "unique_actors": len(actors),
        "actors": actors,
    }


def clear_buffer():
    """Clear the in-memory audit buffer (for testing)."""
    _audit_buffer.clear()
