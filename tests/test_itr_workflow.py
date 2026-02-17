"""Tests for the ITR filing workflow engine."""

import pytest

from app.domain.services.itr_workflow import (
    VALID_TRANSITIONS,
    ALL_STATUSES,
    InvalidTransitionError,
    validate_transition,
    get_itr_notification_message,
)


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS structure tests
# ---------------------------------------------------------------------------

class TestValidTransitionsStructure:

    def test_all_statuses_present(self):
        expected = {"draft", "pending_ca_review", "changes_requested", "ca_approved", "user_confirmed", "filed"}
        assert ALL_STATUSES == expected

    def test_filed_is_terminal(self):
        assert VALID_TRANSITIONS["filed"] == []

    def test_draft_transitions(self):
        allowed = VALID_TRANSITIONS["draft"]
        assert "pending_ca_review" in allowed
        assert "user_confirmed" in allowed

    def test_pending_ca_review_transitions(self):
        allowed = VALID_TRANSITIONS["pending_ca_review"]
        assert "ca_approved" in allowed
        assert "changes_requested" in allowed

    def test_changes_requested_transitions(self):
        allowed = VALID_TRANSITIONS["changes_requested"]
        assert "pending_ca_review" in allowed
        assert "draft" in allowed

    def test_ca_approved_transitions(self):
        allowed = VALID_TRANSITIONS["ca_approved"]
        assert "user_confirmed" in allowed
        assert "filed" in allowed

    def test_user_confirmed_transitions(self):
        allowed = VALID_TRANSITIONS["user_confirmed"]
        assert "filed" in allowed


# ---------------------------------------------------------------------------
# validate_transition tests
# ---------------------------------------------------------------------------

class TestValidateTransition:

    def test_valid_draft_to_pending(self):
        validate_transition("draft", "pending_ca_review")  # should not raise

    def test_valid_draft_to_user_confirmed(self):
        validate_transition("draft", "user_confirmed")

    def test_valid_pending_to_approved(self):
        validate_transition("pending_ca_review", "ca_approved")

    def test_valid_pending_to_changes_requested(self):
        validate_transition("pending_ca_review", "changes_requested")

    def test_valid_changes_requested_to_pending(self):
        validate_transition("changes_requested", "pending_ca_review")

    def test_valid_changes_requested_to_draft(self):
        validate_transition("changes_requested", "draft")

    def test_valid_ca_approved_to_user_confirmed(self):
        validate_transition("ca_approved", "user_confirmed")

    def test_valid_ca_approved_to_filed(self):
        validate_transition("ca_approved", "filed")

    def test_valid_user_confirmed_to_filed(self):
        validate_transition("user_confirmed", "filed")

    def test_invalid_draft_to_filed(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("draft", "filed")

    def test_invalid_draft_to_ca_approved(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("draft", "ca_approved")

    def test_invalid_filed_to_anything(self):
        for status in ALL_STATUSES:
            if status == "filed":
                continue
            with pytest.raises(InvalidTransitionError):
                validate_transition("filed", status)

    def test_invalid_pending_to_draft(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("pending_ca_review", "draft")

    def test_invalid_pending_to_filed(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("pending_ca_review", "filed")

    def test_invalid_user_confirmed_to_draft(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("user_confirmed", "draft")

    def test_invalid_ca_approved_to_draft(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("ca_approved", "draft")

    def test_unknown_current_status(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("nonexistent", "draft")

    def test_error_message_includes_allowed(self):
        with pytest.raises(InvalidTransitionError, match="Allowed"):
            validate_transition("draft", "filed")

    def test_self_transition_not_allowed(self):
        for status in ALL_STATUSES:
            if status in VALID_TRANSITIONS.get(status, []):
                continue  # skip if explicitly allowed
            with pytest.raises(InvalidTransitionError):
                validate_transition(status, status)


# ---------------------------------------------------------------------------
# Workflow path tests (multi-step)
# ---------------------------------------------------------------------------

class TestWorkflowPaths:

    def test_happy_path_with_ca(self):
        """draft -> pending_ca_review -> ca_approved -> user_confirmed -> filed"""
        path = ["draft", "pending_ca_review", "ca_approved", "user_confirmed", "filed"]
        for i in range(len(path) - 1):
            validate_transition(path[i], path[i + 1])

    def test_happy_path_without_ca(self):
        """draft -> user_confirmed -> filed"""
        validate_transition("draft", "user_confirmed")
        validate_transition("user_confirmed", "filed")

    def test_ca_rejects_then_resubmit(self):
        """draft -> pending -> changes_requested -> pending -> ca_approved -> filed"""
        path = ["draft", "pending_ca_review", "changes_requested", "pending_ca_review", "ca_approved", "filed"]
        for i in range(len(path) - 1):
            validate_transition(path[i], path[i + 1])

    def test_changes_requested_back_to_draft(self):
        """draft -> pending -> changes_requested -> draft -> user_confirmed -> filed"""
        path = ["draft", "pending_ca_review", "changes_requested", "draft", "user_confirmed", "filed"]
        for i in range(len(path) - 1):
            validate_transition(path[i], path[i + 1])

    def test_ca_approved_direct_to_filed(self):
        """draft -> pending -> ca_approved -> filed"""
        path = ["draft", "pending_ca_review", "ca_approved", "filed"]
        for i in range(len(path) - 1):
            validate_transition(path[i], path[i + 1])


# ---------------------------------------------------------------------------
# Notification messages
# ---------------------------------------------------------------------------

class TestNotificationMessages:

    def test_pending_ca_review(self):
        msg = get_itr_notification_message("pending_ca_review", "ITR-1")
        assert "ITR-1" in msg
        assert "CA" in msg or "review" in msg

    def test_ca_approved(self):
        msg = get_itr_notification_message("ca_approved", "ITR-4")
        assert "approved" in msg
        assert "ITR-4" in msg

    def test_changes_requested_with_notes(self):
        msg = get_itr_notification_message("changes_requested", "ITR-1", ca_notes="Fix 80C amount")
        assert "changes" in msg.lower()
        assert "Fix 80C amount" in msg

    def test_changes_requested_without_notes(self):
        msg = get_itr_notification_message("changes_requested", "ITR-1")
        assert "changes" in msg.lower()

    def test_user_confirmed(self):
        msg = get_itr_notification_message("user_confirmed", "ITR-1")
        assert "confirmed" in msg.lower()

    def test_filed(self):
        msg = get_itr_notification_message("filed", "ITR-4")
        assert "filed" in msg.lower()
        assert "ITR-4" in msg

    def test_unknown_status_fallback(self):
        msg = get_itr_notification_message("unknown_status", "ITR-1")
        assert "unknown_status" in msg
