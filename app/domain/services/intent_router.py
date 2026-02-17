# app/domain/services/intent_router.py

import logging
from dataclasses import dataclass

from app.infrastructure.external.openai_client import detect_intent

logger = logging.getLogger("intent_router")

# Maps NLP intents to bot state machine states
INTENT_STATE_MAP = {
    "gst_services": "GST_MENU",
    "itr_services": "ITR_MENU",
    "upload_invoice": "WAIT_INVOICE_UPLOAD",
    "change_language": "LANG_MENU",
    "tax_qa": "TAX_QA",
    "tax_insights": "INSIGHTS_MENU",
    "enter_gstin": "WAIT_GSTIN",
    "main_menu": "MAIN_MENU",
    "go_back": "__POP__",
}

# Maps NLP intents to the i18n key for the target state's screen
INTENT_SCREEN_MAP = {
    "gst_services": "GST_SERVICES",
    "itr_services": "ITR_SERVICES",
    "upload_invoice": "UPLOAD_INVOICE_PROMPT",
    "change_language": "LANG_MENU",
    "tax_qa": "TAX_QA_WELCOME",
    "tax_insights": "INSIGHTS_MENU",
    "enter_gstin": "ASK_GSTIN",
    "main_menu": "WELCOME_MENU",
}

CONFIDENCE_THRESHOLD = 0.6


@dataclass
class ResolvedAction:
    target_state: str | None  # e.g. "GST_MENU", "TAX_QA", None if fallback
    i18n_key: str | None  # key for the screen to show
    extracted_entity: str | None  # e.g. a GSTIN detected in the text
    method: str  # "nlp" or "number"


async def resolve_intent(
    text: str,
    lang: str,
    current_state: str,
) -> ResolvedAction:
    """
    Resolve user text to a bot action.

    1. If text is a single digit (0-9), skip NLP and return method="number"
       so the existing number-based routing handles it.
    2. Otherwise, call OpenAI intent detection.
    3. If confidence >= threshold, map intent to a target state.
    4. If confidence is low, return target_state=None so the caller
       falls through to the "unknown input" path.
    """
    # Single-digit inputs: let number-based routing handle them
    if text.strip() in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
        return ResolvedAction(
            target_state=None,
            i18n_key=None,
            extracted_entity=None,
            method="number",
        )

    # Call NLP intent detection
    result = await detect_intent(text, lang)

    if result.confidence >= CONFIDENCE_THRESHOLD and result.intent != "unknown":
        target_state = INTENT_STATE_MAP.get(result.intent)
        i18n_key = INTENT_SCREEN_MAP.get(result.intent)

        return ResolvedAction(
            target_state=target_state,
            i18n_key=i18n_key,
            extracted_entity=result.extracted_entity,
            method="nlp",
        )

    # Low confidence or unknown: fall back to number-based routing
    return ResolvedAction(
        target_state=None,
        i18n_key=None,
        extracted_entity=None,
        method="number",
    )
