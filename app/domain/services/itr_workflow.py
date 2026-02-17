# app/domain/services/itr_workflow.py
"""
ITR Filing Workflow Engine.

Manages the status lifecycle of ITR drafts:
  draft → pending_ca_review → ca_approved → user_confirmed → filed

Handles transitions, validation, and WhatsApp notifications.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.services.itr_form_parser import (
    MergedITRData,
    merged_to_dict,
    dict_to_merged,
    merged_to_itr1_input,
    merged_to_itr4_input,
)
from app.domain.services.itr_service import (
    ITR1Input,
    ITR4Input,
    ITRResult,
    compute_itr1,
    compute_itr4,
)
from app.domain.services.mismatch_detection import report_to_dict
from app.domain.services.document_checklist import checklist_to_dict

logger = logging.getLogger("itr_workflow")


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["pending_ca_review", "user_confirmed"],
    "pending_ca_review": ["ca_approved", "changes_requested"],
    "changes_requested": ["pending_ca_review", "draft"],
    "ca_approved": ["user_confirmed", "filed"],
    "user_confirmed": ["filed"],
    "filed": [],  # terminal
}

ALL_STATUSES = set(VALID_TRANSITIONS.keys())


# ---------------------------------------------------------------------------
# Transition validation
# ---------------------------------------------------------------------------

class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed."""
    pass


def validate_transition(current_status: str, new_status: str) -> None:
    """Raise InvalidTransitionError if the transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed: {allowed}"
        )


# ---------------------------------------------------------------------------
# Workflow operations
# ---------------------------------------------------------------------------

async def transition_itr_draft(
    draft_id: UUID,
    new_status: str,
    db: Any,
    *,
    ca_notes: str | None = None,
    notify_wa_id: str | None = None,
    lang: str = "en",
) -> Any:
    """
    Validate and execute a status transition on an ITR draft.

    Parameters
    ----------
    draft_id : UUID
    new_status : str
    db : AsyncSession
    ca_notes : str, optional
        CA's review notes (for changes_requested).
    notify_wa_id : str, optional
        WhatsApp ID to send notification to.
    lang : str
        Language for notification.

    Returns
    -------
    ITRDraft (updated)

    Raises
    ------
    InvalidTransitionError
        If the transition is not valid.
    """
    from app.infrastructure.db.repositories.itr_draft_repository import ITRDraftRepository

    repo = ITRDraftRepository(db)
    draft = await repo.get_by_id(draft_id)
    if not draft:
        raise ValueError(f"ITR draft {draft_id} not found")

    validate_transition(draft.status, new_status)

    ca_reviewed_at = None
    if new_status in ("ca_approved", "changes_requested"):
        ca_reviewed_at = datetime.now(timezone.utc)

    updated = await repo.update_status(
        draft_id,
        new_status,
        ca_notes=ca_notes,
        ca_reviewed_at=ca_reviewed_at,
    )

    # Send WhatsApp notification
    if notify_wa_id:
        try:
            msg = get_itr_notification_message(
                new_status, draft.form_type, lang, ca_notes=ca_notes
            )
            from app.infrastructure.external.whatsapp_client import send_whatsapp_text
            await send_whatsapp_text(notify_wa_id, msg)
        except Exception:
            logger.exception("Failed to send ITR workflow notification to %s", notify_wa_id)

    return updated


async def create_itr_draft_from_session(
    wa_id: str,
    session: dict[str, Any],
    form_type: str,
    db: Any,
) -> Any:
    """
    Create an ITR draft from the current WhatsApp session data.

    Parameters
    ----------
    wa_id : str
        WhatsApp user number.
    session : dict
        Full session dict with data sub-dict.
    form_type : str
        "ITR-1" or "ITR-4"
    db : AsyncSession

    Returns
    -------
    ITRDraft
    """
    from app.infrastructure.db.repositories.itr_draft_repository import ITRDraftRepository
    from app.infrastructure.db.models import User
    from sqlalchemy import select

    repo = ITRDraftRepository(db)
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

    # Check if user has a CA via BusinessClient
    ca_id = await repo.find_ca_for_user(wa_id)

    # Determine initial status — always queue for review (admin assigns CA if needed)
    initial_status = "pending_ca_review"

    # Extract computation data from session
    itr_data = data.get("itr_last_result", {})
    merged_dict = data.get("itr_docs", {}).get("merged_data")
    pan = ""
    assessment_year = "2025-26"

    if merged_dict:
        pan = merged_dict.get("pan", "")
        assessment_year = merged_dict.get("assessment_year", "2025-26")
    elif form_type == "ITR-1":
        itr1 = data.get("itr1", {})
        pan = itr1.get("pan", "")
    elif form_type == "ITR-2":
        itr2 = data.get("itr2", {})
        pan = itr2.get("pan", "")
    elif form_type == "ITR-4":
        itr4 = data.get("itr4", {})
        pan = itr4.get("pan", "")

    # Collect linked GST filing IDs
    gst_filing_ids = []
    for f in data.get("gst_filings", []):
        if f.get("filing_id"):
            gst_filing_ids.append(str(f["filing_id"]))

    draft = await repo.create(
        user_id=user.id,
        form_type=form_type,
        assessment_year=assessment_year,
        pan=pan,
        ca_id=ca_id,
        status=initial_status,
        input_json=json.dumps(itr_data.get("input"), default=str) if itr_data.get("input") else None,
        result_json=json.dumps(itr_data.get("result"), default=str) if itr_data.get("result") else None,
        merged_data_json=json.dumps(merged_dict, default=str) if merged_dict else None,
        mismatch_json=json.dumps(data.get("itr_docs", {}).get("mismatches"), default=str) if data.get("itr_docs", {}).get("mismatches") else None,
        checklist_json=json.dumps(data.get("itr_docs", {}).get("checklist"), default=str) if data.get("itr_docs", {}).get("checklist") else None,
        linked_gst_filing_ids=gst_filing_ids if gst_filing_ids else None,
    )

    await db.commit()

    # Log draft creation
    if ca_id:
        logger.info(
            "ITR draft %s sent for CA review (ca_id=%s, form=%s)",
            draft.id, ca_id, form_type,
        )
    else:
        logger.info(
            "ITR draft %s queued for CA assignment (form=%s)",
            draft.id, form_type,
        )

    return draft


# ---------------------------------------------------------------------------
# Notification messages
# ---------------------------------------------------------------------------

def get_itr_notification_message(
    status: str,
    form_type: str,
    lang: str = "en",
    ca_notes: str | None = None,
) -> str:
    """Build a WhatsApp notification message for an ITR status change."""
    messages = {
        "pending_ca_review": (
            f"Your {form_type} computation has been sent to your CA for review. "
            "You'll be notified when they respond."
        ),
        "ca_approved": (
            f"Your CA has approved your {form_type}! "
            "You can now download the JSON and file on incometax.gov.in, "
            "or reply YES to confirm."
        ),
        "changes_requested": (
            f"Your CA has requested changes to your {form_type}."
            + (f"\n\nCA Notes: {ca_notes}" if ca_notes else "")
            + "\n\nPlease update your return and resubmit."
        ),
        "user_confirmed": (
            f"You have confirmed your {form_type}. "
            "Your return is ready for filing."
        ),
        "filed": (
            f"Your {form_type} has been filed successfully!"
        ),
    }
    return messages.get(status, f"{form_type} status updated to: {status}")
