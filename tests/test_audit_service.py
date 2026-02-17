# tests/test_audit_service.py
"""Tests for the audit trail service."""

import pytest

from app.domain.services.audit_service import (
    clear_buffer,
    get_access_summary,
    get_recent_audit_entries,
    log_access,
)


def _make_entry(**overrides):
    """Helper to create a log_access call with sensible defaults."""
    defaults = {
        "actor_type": "ca",
        "actor_id": "ca@example.com",
        "action": "view",
        "resource_type": "client",
        "resource_id": "CLI-001",
        "client_gstin": "29ABCDE1234F1Z5",
    }
    defaults.update(overrides)
    return log_access(**defaults)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_log_access_creates_entry():
    """log_access should return an AuditEntry and add it to the buffer."""
    clear_buffer()

    entry = log_access(
        actor_type="admin",
        actor_id="admin@example.com",
        action="view",
        resource_type="invoice",
        resource_id="INV-100",
        client_gstin="07AAACR5055K1Z4",
        details="Viewed invoice details",
        ip_address="10.0.0.1",
    )

    assert entry.actor_type == "admin"
    assert entry.actor_id == "admin@example.com"
    assert entry.action == "view"
    assert entry.resource_type == "invoice"
    assert entry.resource_id == "INV-100"
    assert entry.client_gstin == "07AAACR5055K1Z4"
    assert entry.details == "Viewed invoice details"
    assert entry.ip_address == "10.0.0.1"
    assert entry.timestamp  # non-empty ISO string

    # Should also appear in the buffer
    entries = get_recent_audit_entries(limit=10)
    assert len(entries) == 1
    assert entries[0]["actor_id"] == "admin@example.com"


def test_get_recent_entries_with_limit():
    """get_recent_audit_entries should respect the limit parameter."""
    clear_buffer()

    for i in range(10):
        _make_entry(resource_id=f"CLI-{i:03d}")

    entries = get_recent_audit_entries(limit=5)
    assert len(entries) == 5
    # Most recent first (CLI-009 through CLI-005)
    assert entries[0]["resource_id"] == "CLI-009"
    assert entries[4]["resource_id"] == "CLI-005"


def test_filter_by_actor_type():
    """get_recent_audit_entries should filter by actor_type."""
    clear_buffer()

    _make_entry(actor_type="ca", actor_id="ca@firm.com")
    _make_entry(actor_type="admin", actor_id="admin@firm.com")
    _make_entry(actor_type="system", actor_id="gst_sync")
    _make_entry(actor_type="ca", actor_id="ca2@firm.com")

    ca_entries = get_recent_audit_entries(actor_type="ca")
    assert len(ca_entries) == 2
    assert all(e["actor_type"] == "ca" for e in ca_entries)

    admin_entries = get_recent_audit_entries(actor_type="admin")
    assert len(admin_entries) == 1
    assert admin_entries[0]["actor_id"] == "admin@firm.com"


def test_filter_by_gstin():
    """get_recent_audit_entries should filter by client_gstin."""
    clear_buffer()

    _make_entry(client_gstin="29ABCDE1234F1Z5")
    _make_entry(client_gstin="07AAACR5055K1Z4")
    _make_entry(client_gstin="29ABCDE1234F1Z5")

    entries = get_recent_audit_entries(client_gstin="29ABCDE1234F1Z5")
    assert len(entries) == 2
    assert all(e["client_gstin"] == "29ABCDE1234F1Z5" for e in entries)

    entries_other = get_recent_audit_entries(client_gstin="07AAACR5055K1Z4")
    assert len(entries_other) == 1


def test_get_access_summary():
    """get_access_summary should aggregate accesses per actor for a GSTIN."""
    clear_buffer()

    gstin = "29ABCDE1234F1Z5"
    _make_entry(actor_type="ca", actor_id="ca@firm.com", client_gstin=gstin)
    _make_entry(actor_type="ca", actor_id="ca@firm.com", client_gstin=gstin)
    _make_entry(actor_type="admin", actor_id="admin@firm.com", client_gstin=gstin)
    _make_entry(client_gstin="07AAACR5055K1Z4")  # different GSTIN, should be excluded

    summary = get_access_summary(gstin)
    assert summary["client_gstin"] == gstin
    assert summary["total_accesses"] == 3
    assert summary["unique_actors"] == 2

    ca_key = "ca:ca@firm.com"
    assert ca_key in summary["actors"]
    assert summary["actors"][ca_key]["count"] == 2

    admin_key = "admin:admin@firm.com"
    assert admin_key in summary["actors"]
    assert summary["actors"][admin_key]["count"] == 1


def test_clear_buffer():
    """clear_buffer should remove all entries from the in-memory buffer."""
    clear_buffer()

    _make_entry()
    _make_entry()
    assert len(get_recent_audit_entries()) == 2

    clear_buffer()
    assert len(get_recent_audit_entries()) == 0
