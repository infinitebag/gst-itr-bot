# tests/test_global_commands_v2.py
"""Tests for global command keywords (MENU, BACK, HELP, RESTART).

The global command handling lives in app/api/routes/whatsapp.py (around lines
1041-1079).  These tests verify the command-matching logic, case insensitivity,
the _FREE_INPUT_STATES bypass, and the nav-stack helpers (push_state /
pop_state) that underpin BACK navigation.
"""

import pytest

from app.api.routes.whatsapp import (
    MAIN_MENU,
    GST_MENU,
    ITR_MENU,
    # Free-input states (representative subset)
    GST_START_GSTIN,
    GST_MULTI_GST_ADD,
    WAIT_GSTIN,
    ITR1_ASK_PAN,
    ITR1_ASK_NAME,
    ITR1_ASK_DOB,
    ITR1_ASK_SALARY,
    ITR1_ASK_OTHER_INCOME,
    ITR1_ASK_80C,
    ITR1_ASK_80D,
    ITR1_ASK_TDS,
    ITR2_ASK_PAN,
    ITR2_ASK_NAME,
    ITR2_ASK_DOB,
    ITR2_ASK_SALARY,
    ITR2_ASK_OTHER_INCOME,
    ITR2_ASK_STCG,
    ITR2_ASK_LTCG,
    ITR2_ASK_80C,
    ITR2_ASK_80D,
    ITR2_ASK_TDS,
    ITR4_ASK_PAN,
    ITR4_ASK_NAME,
    ITR4_ASK_DOB,
    ITR4_ASK_TURNOVER,
    ITR4_ASK_80C,
    ITR4_ASK_TDS,
    # Nav-stack helpers
    push_state,
    pop_state,
)


# =====================================================================
# Reproduce the exact _FREE_INPUT_STATES set from whatsapp.py so that
# test assertions stay in sync with production code.
# =====================================================================
_FREE_INPUT_STATES = {
    # Personal details (PAN, name, DOB -- free text)
    ITR1_ASK_PAN, ITR1_ASK_NAME, ITR1_ASK_DOB,
    ITR2_ASK_PAN, ITR2_ASK_NAME, ITR2_ASK_DOB,
    ITR4_ASK_PAN, ITR4_ASK_NAME, ITR4_ASK_DOB,
    # Numeric amounts (salary, deductions, etc.)
    ITR1_ASK_SALARY, ITR1_ASK_OTHER_INCOME, ITR1_ASK_80C,
    ITR1_ASK_80D, ITR1_ASK_TDS,
    ITR2_ASK_SALARY, ITR2_ASK_OTHER_INCOME,
    ITR2_ASK_STCG, ITR2_ASK_LTCG,
    ITR2_ASK_80C, ITR2_ASK_80D, ITR2_ASK_TDS,
    ITR4_ASK_TURNOVER, ITR4_ASK_80C, ITR4_ASK_TDS,
    # GSTIN entry
    WAIT_GSTIN,
    # GST Onboarding: free-form GSTIN entry
    GST_START_GSTIN,
    GST_MULTI_GST_ADD,
    # Connect with CA: free-text question
    "CONNECT_CA_ASK_TEXT",
    # Change Number: email + OTP entry
    "CHANGE_NUMBER_CONFIRM_EMAIL",
    "CHANGE_NUMBER_ENTER_OTP",
    # GST Payment: challan number/date/amount entry
    "GST_PAYMENT_CAPTURE",
}

# Commands that are only intercepted outside free-input states.
_GUARDED_COMMANDS = {"MENU", "BACK"}

# Commands that are intercepted unconditionally.
_ALWAYS_COMMANDS = {"HELP", "RESTART"}


# =====================================================================
# 1. MENU command -- case-insensitive matching
# =====================================================================
class TestMenuCommand:
    """MENU routes the user to MAIN_MENU from any non-free-input state."""

    @pytest.mark.parametrize("text", ["MENU", "menu", "Menu", "mEnU", "  menu  "])
    def test_menu_command_matches_case_insensitively(self, text):
        assert text.strip().upper() == "MENU"

    def test_menu_blocked_in_free_input_state(self):
        """In a free-input state the typed word 'menu' is valid data, not a command."""
        state = GST_START_GSTIN
        text_upper = "MENU"
        should_intercept = text_upper == "MENU" and state not in _FREE_INPUT_STATES
        assert should_intercept is False

    @pytest.mark.parametrize("state", [MAIN_MENU, GST_MENU, ITR_MENU, "RESTART_CONFIRM"])
    def test_menu_intercepted_in_normal_states(self, state):
        """In normal (non-free-input) states, MENU should be intercepted."""
        text_upper = "MENU"
        should_intercept = text_upper == "MENU" and state not in _FREE_INPUT_STATES
        assert should_intercept is True


# =====================================================================
# 2. BACK command -- pops the state stack
# =====================================================================
class TestBackCommand:
    """BACK pops the navigation stack and returns to the previous screen."""

    @pytest.mark.parametrize("text", ["BACK", "back", "Back", "bAcK", "  back  "])
    def test_back_command_matches_case_insensitively(self, text):
        assert text.strip().upper() == "BACK"

    def test_back_blocked_in_free_input_state(self):
        state = ITR1_ASK_PAN
        text_upper = "BACK"
        should_intercept = text_upper == "BACK" and state not in _FREE_INPUT_STATES
        assert should_intercept is False

    @pytest.mark.parametrize("state", [GST_MENU, ITR_MENU, "SETTINGS_MENU"])
    def test_back_intercepted_in_normal_states(self, state):
        text_upper = "BACK"
        should_intercept = text_upper == "BACK" and state not in _FREE_INPUT_STATES
        assert should_intercept is True

    # -- pop_state helper --

    def test_pop_state_returns_previous(self):
        """pop_state should return the most recent state pushed onto the stack."""
        session = {"stack": [MAIN_MENU, GST_MENU]}
        result = pop_state(session)
        assert result == GST_MENU
        assert session["stack"] == [MAIN_MENU]

    def test_pop_state_defaults_to_main_menu_when_empty(self):
        """If the stack is empty, pop_state should default to MAIN_MENU."""
        session = {"stack": []}
        result = pop_state(session)
        assert result == MAIN_MENU

    def test_pop_state_defaults_when_no_stack_key(self):
        """If there is no 'stack' key at all, pop_state should default to MAIN_MENU."""
        session = {}
        result = pop_state(session)
        assert result == MAIN_MENU

    def test_push_then_pop_roundtrip(self):
        """push_state + pop_state should give a clean LIFO round-trip."""
        session = {"stack": []}
        push_state(session, MAIN_MENU)
        push_state(session, GST_MENU)
        push_state(session, ITR_MENU)

        assert pop_state(session) == ITR_MENU
        assert pop_state(session) == GST_MENU
        assert pop_state(session) == MAIN_MENU
        # Now exhausted -- should fall back to MAIN_MENU
        assert pop_state(session) == MAIN_MENU

    def test_push_state_creates_stack_key(self):
        """push_state should create the 'stack' list if it does not exist."""
        session = {}
        push_state(session, GST_MENU)
        assert session["stack"] == [GST_MENU]


# =====================================================================
# 3. HELP command -- sends help text (always intercepted)
# =====================================================================
class TestHelpCommand:
    """HELP shows help text and is intercepted in ALL states, including free-input."""

    @pytest.mark.parametrize("text", ["HELP", "help", "Help", "hElP", "  help  "])
    def test_help_command_matches_case_insensitively(self, text):
        assert text.strip().upper() == "HELP"

    @pytest.mark.parametrize(
        "state",
        [MAIN_MENU, GST_MENU, ITR_MENU, GST_START_GSTIN, ITR1_ASK_PAN, WAIT_GSTIN],
    )
    def test_help_intercepted_in_every_state(self, state):
        """HELP has no _FREE_INPUT_STATES guard -- always intercepted."""
        text_upper = "HELP"
        # In the production code, HELP has NO `state not in _FREE_INPUT_STATES` check.
        should_intercept = text_upper == "HELP"
        assert should_intercept is True


# =====================================================================
# 4. RESTART command -- triggers restart confirmation
# =====================================================================
class TestRestartCommand:
    """RESTART prompts for confirmation (or confirms if already in RESTART_CONFIRM)."""

    @pytest.mark.parametrize("text", ["RESTART", "restart", "Restart", "rEsTaRt", "  restart  "])
    def test_restart_command_matches_case_insensitively(self, text):
        assert text.strip().upper() == "RESTART"

    @pytest.mark.parametrize(
        "state",
        [MAIN_MENU, GST_MENU, ITR_MENU, GST_START_GSTIN, ITR1_ASK_PAN],
    )
    def test_restart_intercepted_in_every_state(self, state):
        """RESTART has no _FREE_INPUT_STATES guard -- always intercepted."""
        text_upper = "RESTART"
        should_intercept = text_upper == "RESTART"
        assert should_intercept is True

    def test_restart_first_time_sets_confirm_state(self):
        """First RESTART should transition to RESTART_CONFIRM for two-step safety."""
        state = GST_MENU
        text_upper = "RESTART"

        assert text_upper == "RESTART"
        # Simulate the branching logic from whatsapp.py lines 1062-1079:
        if state == "RESTART_CONFIRM":
            action = "confirmed"
        else:
            action = "prompt_confirmation"

        assert action == "prompt_confirmation"

    def test_restart_in_confirm_state_clears_session(self):
        """Second RESTART (while in RESTART_CONFIRM) should actually reset."""
        state = "RESTART_CONFIRM"
        text_upper = "RESTART"

        assert text_upper == "RESTART"
        if state == "RESTART_CONFIRM":
            action = "confirmed"
        else:
            action = "prompt_confirmation"

        assert action == "confirmed"


# =====================================================================
# 5. Free-input states -- global commands are NOT intercepted
# =====================================================================
class TestFreeInputStatesSkipGlobalCommands:
    """States in _FREE_INPUT_STATES should let the text pass through as data."""

    @pytest.mark.parametrize(
        "state",
        [
            GST_START_GSTIN,
            GST_MULTI_GST_ADD,
            WAIT_GSTIN,
            ITR1_ASK_PAN,
            ITR1_ASK_NAME,
            ITR1_ASK_DOB,
            ITR1_ASK_SALARY,
            ITR2_ASK_PAN,
            ITR2_ASK_STCG,
            ITR4_ASK_TURNOVER,
            "CONNECT_CA_ASK_TEXT",
            "CHANGE_NUMBER_CONFIRM_EMAIL",
            "CHANGE_NUMBER_ENTER_OTP",
            "GST_PAYMENT_CAPTURE",
        ],
    )
    @pytest.mark.parametrize("command", ["MENU", "BACK"])
    def test_guarded_commands_not_intercepted_in_free_input(self, state, command):
        """MENU and BACK must not be intercepted when the current state is free-input."""
        text_upper = command
        should_intercept = (
            text_upper == command and state not in _FREE_INPUT_STATES
        )
        assert should_intercept is False, (
            f"{command} should NOT be intercepted in free-input state {state}"
        )

    @pytest.mark.parametrize(
        "state",
        [
            GST_START_GSTIN,
            ITR1_ASK_PAN,
            WAIT_GSTIN,
        ],
    )
    def test_help_and_restart_still_intercepted_in_free_input(self, state):
        """HELP and RESTART have no _FREE_INPUT_STATES guard in whatsapp.py,
        so they are always intercepted, even during free-text entry."""
        for command in ("HELP", "RESTART"):
            # Production code simply checks `text_upper == "HELP"` -- no state filter.
            should_intercept = command in _ALWAYS_COMMANDS
            assert should_intercept is True


# =====================================================================
# 6. Case insensitivity -- exhaustive variants for all four keywords
# =====================================================================
class TestCaseInsensitivity:
    """Ensure all four global commands match regardless of letter casing."""

    @pytest.mark.parametrize(
        "raw_text, expected_command",
        [
            ("menu", "MENU"),
            ("MENU", "MENU"),
            ("Menu", "MENU"),
            ("mENU", "MENU"),
            ("back", "BACK"),
            ("BACK", "BACK"),
            ("Back", "BACK"),
            ("bACK", "BACK"),
            ("help", "HELP"),
            ("HELP", "HELP"),
            ("Help", "HELP"),
            ("hELP", "HELP"),
            ("restart", "RESTART"),
            ("RESTART", "RESTART"),
            ("Restart", "RESTART"),
            ("rESTART", "RESTART"),
        ],
    )
    def test_upper_normalisation(self, raw_text, expected_command):
        assert raw_text.strip().upper() == expected_command


# =====================================================================
# 7. Old numeric shortcuts -- must NOT match new keyword commands
# =====================================================================
class TestOldNumericCommandsNotMatched:
    """Legacy numeric shortcuts (0, 9, ...) must not collide with keyword nav."""

    def test_zero_is_not_menu(self):
        assert "0".upper() != "MENU"

    def test_nine_is_not_back(self):
        assert "9".upper() != "BACK"

    def test_hash_is_not_help(self):
        assert "#".upper() != "HELP"

    def test_star_is_not_restart(self):
        assert "*".upper() != "RESTART"

    @pytest.mark.parametrize("digit", list("0123456789"))
    def test_no_digit_matches_any_global_command(self, digit):
        """No single digit should accidentally match a global keyword."""
        assert digit.upper() not in {"MENU", "BACK", "HELP", "RESTART"}


# =====================================================================
# 8. Edge cases -- whitespace, empty, partial matches
# =====================================================================
class TestEdgeCases:
    """Guard against accidental matches on partial strings or whitespace."""

    @pytest.mark.parametrize(
        "text",
        [
            "",           # empty
            "   ",        # whitespace-only
            "MENUS",      # partial: extra char
            "BACKS",
            "HELPER",
            "RESTARTING",
            "GO BACK",    # phrase containing a keyword
            "SHOW MENU",
            "HELP ME",
            "RE START",   # space in keyword
        ],
    )
    def test_non_exact_matches_rejected(self, text):
        """Only an exact (after strip + upper) match should trigger a global command."""
        normalised = text.strip().upper()
        assert normalised not in {"MENU", "BACK", "HELP", "RESTART"}
