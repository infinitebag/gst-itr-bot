# app/domain/services/gst_workflow.py
"""
GST Filing Workflow Engine.

Manages the status lifecycle of GST filing records:
  draft → pending_ca_review → ca_approved → submitted → acknowledged

Handles transitions, validation, and WhatsApp notifications.
All GST filings (regular and NIL) go through mandatory CA review
before submission to MasterGST.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger("gst_workflow")


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["pending_ca_review"],
    "pending_ca_review": ["ca_approved", "changes_requested"],
    "changes_requested": ["pending_ca_review", "draft"],
    "ca_approved": ["submitted"],
    "submitted": ["acknowledged", "error"],
    "error": ["draft"],  # allow retry
    "acknowledged": [],  # terminal
}

ALL_STATUSES = set(VALID_TRANSITIONS.keys())


# ---------------------------------------------------------------------------
# Return-period status transitions (monthly compliance lifecycle)
# ---------------------------------------------------------------------------

PERIOD_VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["data_ready"],
    "data_ready": ["recon_in_progress", "draft"],
    "recon_in_progress": ["reconciled", "data_ready"],
    "reconciled": ["ca_review", "data_ready"],
    "ca_review": ["approved", "reconciled"],
    "approved": ["payment_pending", "ca_review"],
    "payment_pending": ["paid", "approved"],
    "paid": ["filed", "payment_pending"],
    "filed": ["closed"],
    "closed": [],  # terminal
}

ALL_PERIOD_STATUSES = set(PERIOD_VALID_TRANSITIONS.keys())


# ---------------------------------------------------------------------------
# Composition taxpayer transitions (simplified — no recon steps)
# ---------------------------------------------------------------------------

COMPOSITION_PERIOD_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["computed"],
    "computed": ["ca_review", "draft"],
    "ca_review": ["approved", "computed"],
    "approved": ["payment_pending", "ca_review"],
    "payment_pending": ["paid", "approved"],
    "paid": ["filed", "payment_pending"],
    "filed": ["closed"],
    "closed": [],  # terminal
}


# ---------------------------------------------------------------------------
# QRMP taxpayer transitions (same as regular but filing only on quarter-end)
# ---------------------------------------------------------------------------

QRMP_PERIOD_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["data_ready"],
    "data_ready": ["recon_in_progress", "draft"],
    "recon_in_progress": ["reconciled", "data_ready"],
    "reconciled": ["ca_review", "data_ready"],
    "ca_review": ["approved", "reconciled"],
    "approved": ["payment_pending", "ca_review"],
    "payment_pending": ["paid", "approved"],
    "paid": ["filed", "payment_pending"],
    "filed": ["closed"],
    "closed": [],  # terminal
}

# QRMP non-quarter months: only payment tracking
QRMP_NONQUARTER_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["payment_pending"],
    "payment_pending": ["paid", "draft"],
    "paid": ["closed"],
    "closed": [],
}


# ---------------------------------------------------------------------------
# Transition validation
# ---------------------------------------------------------------------------

class InvalidGSTTransitionError(Exception):
    """Raised when a GST filing status transition is not allowed."""
    pass


class InvalidPeriodTransitionError(Exception):
    """Raised when a ReturnPeriod status transition is not allowed."""
    pass


def validate_gst_transition(current_status: str, new_status: str) -> None:
    """Raise InvalidGSTTransitionError if the transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        raise InvalidGSTTransitionError(
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed: {allowed}"
        )


def validate_period_transition(
    current_status: str,
    new_status: str,
    filing_mode: str = "monthly",
    is_quarter_end: bool = True,
) -> None:
    """Raise InvalidPeriodTransitionError if the period transition is not allowed.

    Selects the correct transition table based on filing_mode:
    - "monthly" (regular) → PERIOD_VALID_TRANSITIONS
    - "composition"       → COMPOSITION_PERIOD_TRANSITIONS
    - "qrmp" quarter-end  → QRMP_PERIOD_TRANSITIONS
    - "qrmp" non-quarter  → QRMP_NONQUARTER_TRANSITIONS
    """
    if filing_mode == "composition":
        transitions = COMPOSITION_PERIOD_TRANSITIONS
    elif filing_mode == "qrmp" and not is_quarter_end:
        transitions = QRMP_NONQUARTER_TRANSITIONS
    elif filing_mode == "qrmp":
        transitions = QRMP_PERIOD_TRANSITIONS
    else:
        transitions = PERIOD_VALID_TRANSITIONS

    allowed = transitions.get(current_status, [])
    if new_status not in allowed:
        raise InvalidPeriodTransitionError(
            f"Cannot transition period from '{current_status}' to '{new_status}' "
            f"(mode={filing_mode}). Allowed: {allowed}"
        )


# ---------------------------------------------------------------------------
# Workflow operations
# ---------------------------------------------------------------------------

async def transition_gst_filing(
    filing_id: UUID,
    new_status: str,
    db: Any,
    *,
    ca_notes: str | None = None,
    reference_number: str | None = None,
    response_json: dict | None = None,
    notify_wa_id: str | None = None,
    lang: str = "en",
) -> Any:
    """
    Validate and execute a status transition on a GST filing record.

    Parameters
    ----------
    filing_id : UUID
    new_status : str
    db : AsyncSession
    ca_notes : str, optional
        CA's review notes (for changes_requested).
    reference_number : str, optional
        Acknowledgement number (for submitted/acknowledged).
    response_json : dict, optional
        API response (for submitted/acknowledged).
    notify_wa_id : str, optional
        WhatsApp ID to send notification to.
    lang : str
        Language for notification.

    Returns
    -------
    FilingRecord (updated)
    """
    from app.infrastructure.db.repositories.filing_repository import FilingRepository

    repo = FilingRepository(db)
    filing = await repo.get_by_id(filing_id)
    if not filing:
        raise ValueError(f"GST filing {filing_id} not found")

    validate_gst_transition(filing.status, new_status)

    ca_reviewed_at = None
    if new_status in ("ca_approved", "changes_requested"):
        ca_reviewed_at = datetime.now(timezone.utc)

    filed_at = None
    if new_status in ("submitted", "acknowledged"):
        filed_at = datetime.now(timezone.utc)

    updated = await repo.update_ca_review(
        filing_id,
        new_status,
        ca_notes=ca_notes,
        ca_reviewed_at=ca_reviewed_at,
        reference_number=reference_number,
        response=response_json,
        filed_at=filed_at,
    )

    # Send WhatsApp notification
    if notify_wa_id:
        try:
            form_type = filing.form_type
            period = filing.period or ""
            msg = get_gst_notification_message(
                new_status, form_type, lang,
                ca_notes=ca_notes, period=period,
            )
            from app.infrastructure.external.whatsapp_client import send_whatsapp_text
            await send_whatsapp_text(notify_wa_id, msg)
        except Exception:
            logger.exception(
                "Failed to send GST workflow notification to %s", notify_wa_id
            )

    return updated


async def create_gst_draft_from_session(
    wa_id: str,
    session: dict[str, Any],
    form_type: str,
    db: Any,
    *,
    is_nil: bool = False,
) -> Any:
    """
    Create a GST filing draft from the current WhatsApp session data
    and auto-send to CA for review.

    Parameters
    ----------
    wa_id : str
        WhatsApp user number.
    session : dict
        Full session dict with data sub-dict.
    form_type : str
        "GSTR-3B", "GSTR-1", or "GSTR-3B + GSTR-1" (for combined NIL).
    db : AsyncSession
    is_nil : bool
        Whether this is a NIL filing.

    Returns
    -------
    FilingRecord
    """
    from app.infrastructure.db.repositories.filing_repository import FilingRepository
    from app.infrastructure.db.models import User, BusinessClient
    from sqlalchemy import select

    repo = FilingRepository(db)
    data = session.get("data", {})

    # Find or create user
    stmt = select(User).where(User.whatsapp_number == wa_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        user = User(whatsapp_number=wa_id)
        db.add(user)
        await db.flush()
        logger.info("Auto-created User record for WhatsApp %s (id=%s)", wa_id, user.id)

    # Find CA via BusinessClient
    ca_id = await repo.find_ca_for_whatsapp(wa_id)

    gstin = data.get("gstin", "")

    # Determine period
    from app.domain.services.gst_service import get_current_gst_period
    period = data.get("nil_period") or data.get("gst_period") or get_current_gst_period()

    # Build payload
    payload: dict[str, Any] = {
        "is_nil": is_nil,
        "form_type": form_type,
        "gstin": gstin,
        "period": period,
    }

    if is_nil:
        payload["nil_form_type"] = data.get("nil_form_type", form_type)
    else:
        # Include invoice data for CA review
        # Note: uploaded_invoices already contains every invoice (including
        # last_invoice) thanks to _upsert_invoice dedup during upload.
        # Do NOT re-add last_invoice — that was causing duplicates on the
        # CA dashboard.
        invoices = data.get("uploaded_invoices", [])
        payload["invoices"] = invoices

        # Include summary if available
        gst_filing_form = data.get("gst_filing_form", form_type)
        if gst_filing_form == "GSTR-3B":
            summary = data.get("gstr3b_summary")
            if summary:
                payload["gstr3b_summary"] = summary
        elif gst_filing_form == "GSTR-1":
            summary = data.get("gstr1_summary")
            if summary:
                payload["gstr1_summary"] = summary

    # Determine initial status — always queue for review (admin assigns CA if needed)
    initial_status = "pending_ca_review"

    record = await repo.create_record(
        user_id=user.id,
        filing_type="GST",
        form_type=form_type,
        period=period,
        gstin=gstin,
        status=initial_status,
        payload=payload,
        ca_id=ca_id,
    )

    logger.info(
        "GST filing draft %s created (ca_id=%s, form=%s, period=%s, nil=%s, status=%s, queued=%s)",
        record.id, ca_id, form_type, period, is_nil, initial_status, ca_id is None,
    )

    return record


async def resubmit_gst_filing(
    wa_id: str,
    session: dict,
    db: Any,
) -> Any | None:
    """
    Find a 'changes_requested' GST filing for the user and resubmit it
    with updated invoices from the session.

    Returns the updated FilingRecord or None if no filing to resubmit.
    """
    from app.infrastructure.db.repositories.filing_repository import FilingRepository

    repo = FilingRepository(db)

    # Find user
    stmt = select(User).where(User.whatsapp_number == wa_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return None

    # Find the most recent changes_requested filing
    filing = await repo.get_changes_requested(user.id, filing_type="GST")
    if not filing:
        return None

    # Build updated payload from session invoices
    data = session.get("data", {})
    invoices = data.get("uploaded_invoices", [])

    import json as _json
    existing_payload = {}
    if filing.payload_json:
        try:
            existing_payload = _json.loads(filing.payload_json)
        except (ValueError, TypeError):
            pass

    existing_payload["invoices"] = invoices

    # Resubmit: update payload and transition to pending_ca_review
    updated = await repo.resubmit_with_payload(filing.id, existing_payload)

    if updated:
        logger.info(
            "GST filing %s resubmitted (ca_id=%s, form=%s, period=%s, invoices=%d)",
            updated.id, updated.ca_id, updated.form_type, updated.period, len(invoices),
        )

        # Notify user
        try:
            from app.infrastructure.external.whatsapp_client import send_whatsapp_text
            lang = session.get("lang", "en")
            from app.domain.i18n import t as _i18n_t
            msg = _i18n_t("GST_RESUBMITTED", lang,
                          form_type=updated.form_type,
                          period=updated.period or "")
            await send_whatsapp_text(wa_id, msg)
        except Exception:
            logger.exception("Failed to send resubmit notification to %s", wa_id)

    return updated


# ---------------------------------------------------------------------------
# Notification messages
# ---------------------------------------------------------------------------

def get_gst_notification_message(
    status: str,
    form_type: str,
    lang: str = "en",
    ca_notes: str | None = None,
    period: str = "",
) -> str:
    """Build a WhatsApp notification message for a GST status change."""
    period_str = f" for period {period}" if period else ""

    messages = {
        "pending_ca_review": (
            f"Your {form_type}{period_str} has been sent to your CA for review. "
            "You will be notified when they respond."
        ),
        "ca_approved": (
            f"Your CA has approved your {form_type}{period_str}! "
            "It will now be submitted to the GST portal."
        ),
        "changes_requested": (
            f"Your CA has requested changes to your {form_type}{period_str}."
            + (f"\n\nCA Notes: {ca_notes}" if ca_notes else "")
            + "\n\nPlease update and resubmit."
        ),
        "submitted": (
            f"Your {form_type}{period_str} has been submitted to the GST portal!"
        ),
        "acknowledged": (
            f"Your {form_type}{period_str} has been acknowledged by the GST portal."
        ),
        "error": (
            f"There was an error submitting your {form_type}{period_str}. "
            "Your CA will review and retry."
        ),
    }
    return messages.get(status, f"{form_type} status updated to: {status}")
