import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Dict, Any

from fastapi import APIRouter, Request, Response

from app.core.config import settings
from app.infrastructure.cache.session_cache import SessionCache
from app.infrastructure.external.whatsapp_media import (
    get_media_url,
    download_media,
    upload_media,
    send_whatsapp_document,
)
from app.domain.services.invoice_parser import parse_invoice_text
from app.domain.services.gstin_pan_validation import is_valid_gstin
from app.domain.i18n import t as i18n_t, LANG_NAMES, SUPPORTED_LANGS, get_intent_description
from app.domain.services.intent_router import resolve_intent
from app.domain.services.voice_handler import process_voice_message
from app.infrastructure.external.openai_client import (
    tax_qa as llm_tax_qa,
    parse_invoice_vision,
    parse_invoice_llm,
    parse_form16_vision,
    parse_form16_text,
    parse_form26as_vision,
    parse_form26as_text,
    parse_ais_vision,
    parse_ais_text,
)
from app.domain.services.itr_form_parser import (
    MergedITRData,
    dict_to_parsed_form16,
    dict_to_parsed_form26as,
    dict_to_parsed_ais,
    merge_form16,
    merge_form26as,
    merge_ais,
    format_review_summary,
    merged_to_itr1_input,
    merged_to_itr2_input,
    merged_to_itr4_input,
    merged_to_dict,
    dict_to_merged,
)
from app.infrastructure.ocr.tesseract_backend import (
    extract_text_from_invoice_bytes as ocr_extract,
)
from app.domain.services.tax_analytics import (
    aggregate_invoices,
    detect_anomalies_dynamic as detect_anomalies,
    get_filing_deadlines,
    generate_ai_insights,
)
from app.domain.services.itr_service import (
    ITR1Input,
    ITR2Input,
    ITR4Input,
    compute_itr1_dynamic as compute_itr1,
    compute_itr2_dynamic as compute_itr2,
    compute_itr4_dynamic as compute_itr4,
    format_itr_result,
)
from app.domain.services.gst_service import (
    prepare_gstr3b,
    prepare_nil_gstr3b,
    prepare_nil_gstr1,
    get_current_gst_period,
    file_nil_return_mastergst,
    is_mastergst_configured,
    file_gstr3b_from_session,
    file_gstr1_from_session,
)
from app.domain.services.itr_filing_service import (
    submit_itr_to_sandbox,
    is_itr_sandbox_configured,
)
from app.domain.services.itr_pdf import generate_itr1_pdf, generate_itr4_pdf
from app.domain.services.itr_json import (
    generate_itr1_json,
    generate_itr4_json,
    generate_itr1_efiling_json,
    generate_itr4_efiling_json,
    itr_json_to_string,
)
from app.domain.services.mismatch_detection import (
    detect_mismatches,
    format_mismatch_report,
    report_to_dict,
)
from app.domain.services.document_checklist import (
    generate_checklist,
    format_checklist,
    checklist_to_dict,
)
from app.domain.services.gst_itr_linker import (
    get_gst_data_from_session,
    gst_link_to_dict,
)
from app.infrastructure.external.whatsapp_client import (
    send_whatsapp_text,
    send_whatsapp_document as send_whatsapp_document_bytes,
)
from app.domain.services.invoice_pdf import (
    generate_invoice_pdf,
    generate_multi_invoice_summary_pdf,
)

logger = logging.getLogger("whatsapp")

router = APIRouter(prefix="", tags=["whatsapp"])

session_cache = SessionCache(settings.REDIS_URL)

# =========================
# STATES
# =========================
MAIN_MENU = "MAIN_MENU"
CHOOSE_LANG = "CHOOSE_LANG"
GST_MENU = "GST_MENU"
ITR_MENU = "ITR_MENU"
LANG_MENU = "LANG_MENU"
WAIT_GSTIN = "WAIT_GSTIN"
WAIT_INVOICE_UPLOAD = "WAIT_INVOICE_UPLOAD"
TAX_QA = "TAX_QA"
INSIGHTS_MENU = "INSIGHTS_MENU"

# ITR-1 flow states (personal details → income → deductions → TDS)
ITR1_ASK_PAN = "ITR1_ASK_PAN"
ITR1_ASK_NAME = "ITR1_ASK_NAME"
ITR1_ASK_DOB = "ITR1_ASK_DOB"
ITR1_ASK_GENDER = "ITR1_ASK_GENDER"
ITR1_ASK_SALARY = "ITR1_ASK_SALARY"
ITR1_ASK_OTHER_INCOME = "ITR1_ASK_OTHER_INCOME"
ITR1_ASK_80C = "ITR1_ASK_80C"
ITR1_ASK_80D = "ITR1_ASK_80D"
ITR1_ASK_TDS = "ITR1_ASK_TDS"

# ITR-4 flow states (personal details → type → turnover → deductions → TDS)
ITR4_ASK_PAN = "ITR4_ASK_PAN"
ITR4_ASK_NAME = "ITR4_ASK_NAME"
ITR4_ASK_DOB = "ITR4_ASK_DOB"
ITR4_ASK_GENDER = "ITR4_ASK_GENDER"
ITR4_ASK_TYPE = "ITR4_ASK_TYPE"
ITR4_ASK_TURNOVER = "ITR4_ASK_TURNOVER"
ITR4_ASK_80C = "ITR4_ASK_80C"
ITR4_ASK_TDS = "ITR4_ASK_TDS"

# ITR-2 flow states (personal details → income → capital gains → deductions → TDS)
ITR2_ASK_PAN = "ITR2_ASK_PAN"
ITR2_ASK_NAME = "ITR2_ASK_NAME"
ITR2_ASK_DOB = "ITR2_ASK_DOB"
ITR2_ASK_GENDER = "ITR2_ASK_GENDER"
ITR2_ASK_SALARY = "ITR2_ASK_SALARY"
ITR2_ASK_OTHER_INCOME = "ITR2_ASK_OTHER_INCOME"
ITR2_ASK_STCG = "ITR2_ASK_STCG"
ITR2_ASK_LTCG = "ITR2_ASK_LTCG"
ITR2_ASK_80C = "ITR2_ASK_80C"
ITR2_ASK_80D = "ITR2_ASK_80D"
ITR2_ASK_TDS = "ITR2_ASK_TDS"

# Smart form routing states
ITR_ROUTE_ASK_CG = "ITR_ROUTE_ASK_CG"
ITR_ROUTE_ASK_BIZ = "ITR_ROUTE_ASK_BIZ"
ITR_ROUTE_RESULT = "ITR_ROUTE_RESULT"
ITR_ROUTE_CHOOSE_FORM = "ITR_ROUTE_CHOOSE_FORM"

# ITR document upload flow states
ITR_DOC_TYPE_MENU = "ITR_DOC_TYPE_MENU"
ITR_DOC_UPLOAD = "ITR_DOC_UPLOAD"
ITR_DOC_REVIEW = "ITR_DOC_REVIEW"
ITR_DOC_EDIT_FIELD = "ITR_DOC_EDIT_FIELD"
ITR_DOC_PICK_ITR = "ITR_DOC_PICK_ITR"

# Document type labels for i18n
_DOC_TYPE_LABELS = {
    "form16": "Form 16",
    "26as": "Form 26AS",
    "ais": "AIS",
}

# GST filing states
GST_FILING_MENU = "GST_FILING_MENU"
GST_FILING_CONFIRM = "GST_FILING_CONFIRM"

# ITR filing download state
ITR_FILING_DOWNLOAD = "ITR_FILING_DOWNLOAD"

# GST-ITR linking state
ITR4_GST_LINK_CONFIRM = "ITR4_GST_LINK_CONFIRM"

# Batch upload state (kept for backward compat)
BATCH_UPLOAD = "BATCH_UPLOAD"

# Smart upload (merged single + batch)
SMART_UPLOAD = "SMART_UPLOAD"

# Settings & Account states
SETTINGS_MENU = "SETTINGS_MENU"

# NIL filing states
NIL_FILING_MENU = "NIL_FILING_MENU"
NIL_FILING_CONFIRM = "NIL_FILING_CONFIRM"

# Monthly compliance states
GST_PERIOD_MENU = "GST_PERIOD_MENU"
GST_PERIOD_STATUS = "GST_PERIOD_STATUS"
GST_UPLOAD_PURCHASE = "GST_UPLOAD_PURCHASE"
GST_2B_IMPORT = "GST_2B_IMPORT"
GST_RECON_RESULT = "GST_RECON_RESULT"
GST_LIABILITY = "GST_LIABILITY"
GST_RECON_MISMATCH = "GST_RECON_MISMATCH"

# Phase 2: Additional states
GST_PAYMENT_ENTRY = "GST_PAYMENT_ENTRY"
GST_COMPOSITION_MENU = "GST_COMPOSITION_MENU"
GST_QRMP_MENU = "GST_QRMP_MENU"
GST_RISK_REVIEW = "GST_RISK_REVIEW"
GST_ANNUAL_MENU = "GST_ANNUAL_MENU"

# Phase 4: Segment onboarding states
SEGMENT_ASK_TURNOVER = "SEGMENT_ASK_TURNOVER"
SEGMENT_ASK_INVOICES = "SEGMENT_ASK_INVOICES"
SEGMENT_ASK_EXPORT = "SEGMENT_ASK_EXPORT"
SEGMENT_CONFIRM = "SEGMENT_CONFIRM"

# Phase 6: e-Invoice flow states
EINVOICE_MENU = "EINVOICE_MENU"
EINVOICE_UPLOAD = "EINVOICE_UPLOAD"
EINVOICE_REVIEW = "EINVOICE_REVIEW"
EINVOICE_CONFIRM = "EINVOICE_CONFIRM"
EINVOICE_RESULT = "EINVOICE_RESULT"
EINVOICE_CANCEL = "EINVOICE_CANCEL"
EINVOICE_STATUS_ASK = "EINVOICE_STATUS_ASK"

# Phase 6: e-WayBill flow states
EWAYBILL_MENU = "EWAYBILL_MENU"
EWAYBILL_UPLOAD = "EWAYBILL_UPLOAD"
EWAYBILL_TRANSPORT = "EWAYBILL_TRANSPORT"
EWAYBILL_REVIEW = "EWAYBILL_REVIEW"
EWAYBILL_RESULT = "EWAYBILL_RESULT"
EWAYBILL_TRACK_ASK = "EWAYBILL_TRACK_ASK"
EWAYBILL_VEHICLE_ASK = "EWAYBILL_VEHICLE_ASK"

# Phase 7: Small segment wizard states
SMALL_WIZARD_SALES = "SMALL_WIZARD_SALES"
SMALL_WIZARD_PURCHASES = "SMALL_WIZARD_PURCHASES"
SMALL_WIZARD_SUMMARY = "SMALL_WIZARD_SUMMARY"
SMALL_WIZARD_CONFIRM = "SMALL_WIZARD_CONFIRM"

# Phase 7: Medium segment credit check states
MEDIUM_CREDIT_CHECK = "MEDIUM_CREDIT_CHECK"
MEDIUM_CREDIT_RESULT = "MEDIUM_CREDIT_RESULT"
MEDIUM_MISSING_BILLS = "MEDIUM_MISSING_BILLS"

# Phase 7: Filing status
GST_FILING_STATUS = "GST_FILING_STATUS"

# Phase 8: Multi-GSTIN states
MULTI_GSTIN_MENU = "MULTI_GSTIN_MENU"
MULTI_GSTIN_ADD = "MULTI_GSTIN_ADD"
MULTI_GSTIN_LABEL = "MULTI_GSTIN_LABEL"
MULTI_GSTIN_SUMMARY = "MULTI_GSTIN_SUMMARY"

# Phase 9: Refund & Notice states
REFUND_MENU = "REFUND_MENU"
REFUND_TYPE = "REFUND_TYPE"
REFUND_DETAILS = "REFUND_DETAILS"
REFUND_CONFIRM = "REFUND_CONFIRM"
NOTICE_MENU = "NOTICE_MENU"
NOTICE_UPLOAD = "NOTICE_UPLOAD"
NOTICE_REVIEW = "NOTICE_REVIEW"

# Phase 9: Export services
EXPORT_MENU = "EXPORT_MENU"

# Phase 10: Notification settings
NOTIFICATION_SETTINGS = "NOTIFICATION_SETTINGS"

# Navigation redesign: new states
CONNECT_CA_MENU = "CONNECT_CA_MENU"

# GST Onboarding flow states (Phase 2)
GST_START_GSTIN = "GST_START_GSTIN"
GST_GSTIN_CONFIRM = "GST_GSTIN_CONFIRM"
GST_FILING_FREQUENCY = "GST_FILING_FREQUENCY"
GST_TURNOVER_BAND = "GST_TURNOVER_BAND"
GST_MULTI_GST_CHECK = "GST_MULTI_GST_CHECK"
GST_MULTI_GST_ADD = "GST_MULTI_GST_ADD"
GST_SEGMENT_DONE = "GST_SEGMENT_DONE"

# Language number mapping
LANG_NUMBER_MAP = {"1": "en", "2": "hi", "3": "gu", "4": "ta", "5": "te", "6": "kn"}


# =========================
# i18n helper
# =========================
def _get_lang(session: Dict[str, Any]) -> str:
    lang = session.get("lang") or "en"
    return lang if lang in SUPPORTED_LANGS else "en"


def _t(session: Dict[str, Any], key: str, **kwargs) -> str:
    return i18n_t(key, _get_lang(session), **kwargs)


# =========================
# Webhook signature verification
# =========================
_signature_warning_logged = False


def _verify_webhook_signature(body: bytes, signature_header: str | None) -> bool:
    global _signature_warning_logged
    app_secret = settings.WHATSAPP_APP_SECRET
    if not app_secret:
        # In dev mode, allow unsigned — but warn loudly (once)
        if not _signature_warning_logged:
            logger.warning(
                "WHATSAPP_APP_SECRET is not set — webhook signature verification "
                "is DISABLED. Set it in .env before going to production!"
            )
            _signature_warning_logged = True
        if settings.ENV not in ("dev", "development", "test"):
            logger.error("Rejecting unsigned webhook in non-dev environment (ENV=%s)", settings.ENV)
            return False
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = signature_header[7:]
    computed_sig = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_sig, expected_sig)


# =========================
# Send helper
# =========================
async def _send(wa_id: str, text: str) -> None:
    await send_whatsapp_text(wa_id, text)


async def _send_menu_result(wa_id: str, menu_result) -> None:
    """Send a menu result that could be plain text or an interactive list dict."""
    if isinstance(menu_result, dict) and menu_result.get("type") == "list":
        from app.infrastructure.external.whatsapp_client import send_whatsapp_list
        await send_whatsapp_list(
            wa_id,
            menu_result["body"],
            menu_result["sections"],
            button_text=menu_result.get("button_text", "Choose"),
            header=menu_result.get("header"),
            footer=menu_result.get("footer"),
        )
    else:
        await send_whatsapp_text(wa_id, str(menu_result))


async def _send_buttons(wa_id: str, body: str, buttons: list[dict], header: str = None, footer: str = None) -> None:
    """Helper to send WhatsApp interactive button messages."""
    from app.infrastructure.external.whatsapp_client import send_whatsapp_buttons
    await send_whatsapp_buttons(wa_id, body, buttons, header=header, footer=footer)


async def _rag_tax_qa_answer(
    question: str, lang: str, qa_history: list[dict] | None = None
) -> str:
    """
    RAG-enhanced tax Q&A — tries knowledge base first, falls back to vanilla.

    Returns the answer string (with source references appended if RAG was used).
    """
    try:
        from app.core.db import get_db as _get_db
        from app.domain.services.rag_tax_qa import rag_tax_qa as _rag_qa

        db_session = None
        async for db in _get_db():
            db_session = db
            break
        result = await _rag_qa(question, lang, qa_history, db_session)
        answer = result.answer
        if result.sources and result.used_rag:
            source_refs = "\n".join(
                f"📖 {s['title']}" for s in result.sources[:3]
            )
            answer += f"\n\n---\nSources:\n{source_refs}"
        return answer
    except Exception:
        # Fallback to vanilla GPT-4o
        return await llm_tax_qa(question, lang, qa_history)


# =========================
# Nav stack helpers
# =========================
def push_state(session: Dict[str, Any], state: str) -> None:
    session.setdefault("stack", []).append(state)


def pop_state(session: Dict[str, Any]) -> str:
    stack = session.get("stack", [])
    return stack.pop() if stack else MAIN_MENU


def _upsert_invoice(invoice_list: list, new_inv: dict) -> bool:
    """Replace an existing invoice if same invoice_number (+ supplier_gstin) is found.

    Returns True if an existing invoice was updated, False if it was a new add.
    Match criteria (in priority order):
      1. invoice_number + supplier_gstin both match  (strongest)
      2. invoice_number matches (when supplier_gstin is missing on either side)
    If no match, append as new.
    """
    new_num = (new_inv.get("invoice_number") or "").strip()
    if not new_num:
        # No invoice number extracted → can't deduplicate, always append
        invoice_list.append(new_inv)
        return False

    new_gstin = (new_inv.get("supplier_gstin") or "").strip().upper()

    for idx, existing in enumerate(invoice_list):
        ex_num = (existing.get("invoice_number") or "").strip()
        if not ex_num or ex_num != new_num:
            continue
        # invoice_number matches — check supplier_gstin
        ex_gstin = (existing.get("supplier_gstin") or "").strip().upper()
        if new_gstin and ex_gstin and new_gstin != ex_gstin:
            continue  # same inv number but different supplier → different invoice
        # Match found → replace in-place
        invoice_list[idx] = new_inv
        return True

    # No match found → append
    invoice_list.append(new_inv)
    return False


def _detect_gst_form(invoices: list[dict], user_gstin: str) -> str:
    """Auto-detect whether invoices are for GSTR-3B or GSTR-1.

    Logic:
    - If the user's GSTIN matches supplier_gstin on most invoices,
      these are *outward* (sales) invoices → GSTR-1.
    - If the user's GSTIN matches receiver_gstin (or supplier_gstin
      doesn't match), these are *inward* (purchase) invoices → GSTR-3B.
    - If no GSTIN is set, default to GSTR-3B (most common for small
      businesses uploading purchase invoices for ITC).
    """
    if not invoices:
        return "GSTR-3B"

    if not user_gstin:
        return "GSTR-3B"

    norm_gstin = user_gstin.strip().upper()
    outward = 0  # supplier == user (user sold)
    inward = 0   # supplier != user (user bought)

    for inv in invoices:
        s_gstin = (inv.get("supplier_gstin") or "").strip().upper()
        if s_gstin == norm_gstin:
            outward += 1
        else:
            inward += 1

    # If majority are outward → GSTR-1, else GSTR-3B
    if outward > inward:
        return "GSTR-1"
    return "GSTR-3B"


def _detect_itr_form(merged_data: dict) -> str:
    """Auto-detect ITR form from parsed/merged document data.

    Checks for capital gains → ITR-2, business income → ITR-4, default → ITR-1.
    """
    cg_fields = [
        "stcg_equity", "ltcg_equity", "stcg_other", "ltcg_other",
        "capital_gains", "short_term_cg", "long_term_cg",
    ]
    has_capital_gains = any(
        merged_data.get(f) and float(merged_data.get(f, 0) or 0) > 0
        for f in cg_fields
    )

    biz_fields = ["business_income", "business_turnover", "gross_turnover", "professional_income"]
    has_business = any(
        merged_data.get(f) and float(merged_data.get(f, 0) or 0) > 0
        for f in biz_fields
    )

    if has_capital_gains:
        return "ITR-2"
    elif has_business:
        return "ITR-4"
    return "ITR-1"


async def show_main_menu(wa_id: str, session: Dict[str, Any]) -> None:
    session["state"] = MAIN_MENU
    session["stack"] = []
    await session_cache.save_session(wa_id, session)
    await _send(wa_id, _t(session, "WELCOME_MENU"))


# =========================
# Numeric input helper
# =========================
def _parse_number(text: str) -> float | None:
    """Parse a number from user text, stripping commas and currency symbols."""
    cleaned = text.replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


# =========================
# Invoice display helper
# =========================
def invoice_to_text(session: Dict[str, Any], d: Dict[str, Any]) -> str:
    """Build a rich invoice summary from parsed data."""
    lang = _get_lang(session)
    nav = {"en": "MENU = Main Menu\nBACK = Go Back", "hi": "MENU = मुख्य मेनू\nBACK = पीछे",
           "gu": "MENU = મુખ્ય મેનુ\nBACK = પાછા", "ta": "MENU = முதன்மை பட்டி\nBACK = பின்செல்",
           "te": "MENU = మెయిన్ మెనూ\nBACK = వెనక్కి", "kn": "MENU = ಮುಖ್ಯ ಮೆನು\nBACK = ಹಿಂದೆ"}.get(lang, "MENU = Main Menu\nBACK = Go Back")

    def _fmt(val, prefix=""):
        if val is None:
            return "—"
        if isinstance(val, (int, float)):
            return f"{prefix}{val:,.2f}"
        return str(val)

    def _check(gstin_val, valid_val):
        if gstin_val is None:
            return "—"
        mark = " ✓" if valid_val else (" ✗" if valid_val is False else "")
        return f"{gstin_val}{mark}"

    lines = [_t(session, "INVOICE_PARSED_TITLE"), ""]

    # Supplier info
    if d.get("supplier_name"):
        lines.append(f"Supplier: {d['supplier_name']}")
    lines.append(f"Supplier GSTIN: {_check(d.get('supplier_gstin'), d.get('supplier_gstin_valid'))}")

    # Receiver info
    if d.get("receiver_name"):
        lines.append(f"Buyer: {d['receiver_name']}")
    lines.append(f"Buyer GSTIN: {_check(d.get('receiver_gstin'), d.get('receiver_gstin_valid'))}")

    lines.append("")
    lines.append(f"Invoice No: {_fmt(d.get('invoice_number'))}")
    lines.append(f"Date: {_fmt(d.get('invoice_date'))}")

    if d.get("hsn_code"):
        lines.append(f"HSN/SAC: {d['hsn_code']}")
    if d.get("item_description"):
        desc = str(d["item_description"])
        lines.append(f"Item: {desc[:80]}")

    if d.get("place_of_supply"):
        lines.append(f"Place of Supply: {d['place_of_supply']}")

    lines.append("")
    lines.append(f"Taxable Value: {_fmt(d.get('taxable_value'), '₹')}")

    # Tax breakdown
    if d.get("cgst_amount") is not None and d.get("sgst_amount") is not None:
        lines.append(f"  CGST: {_fmt(d.get('cgst_amount'), '₹')}")
        lines.append(f"  SGST: {_fmt(d.get('sgst_amount'), '₹')}")
    if d.get("igst_amount") is not None:
        lines.append(f"  IGST: {_fmt(d.get('igst_amount'), '₹')}")
    if d.get("tax_rate") is not None:
        lines.append(f"  GST Rate: {d['tax_rate']}%")

    lines.append(f"Tax Amount: {_fmt(d.get('tax_amount'), '₹')}")
    lines.append(f"*Total: {_fmt(d.get('total_amount'), '₹')}*")

    lines.append("")
    lines.append(nav)
    return "\n".join(lines)


# =========================
# State-to-screen-key map
# =========================
def _state_to_screen_key(state: str) -> str:
    return {
        CHOOSE_LANG: "CHOOSE_LANG",
        MAIN_MENU: "WELCOME_MENU",
        GST_MENU: "GST_SERVICES",
        ITR_MENU: "ITR_SERVICES",
        LANG_MENU: "LANG_MENU",
        WAIT_GSTIN: "ASK_GSTIN",
        WAIT_INVOICE_UPLOAD: "UPLOAD_INVOICE_PROMPT",
        TAX_QA: "TAX_QA_WELCOME",
        CONNECT_CA_MENU: "CONNECT_CA_MENU",
        GST_START_GSTIN: "GST_ONBOARD_ASK_GSTIN",
        GST_GSTIN_CONFIRM: "GST_ONBOARD_CONFIRM",
        GST_FILING_FREQUENCY: "GST_ONBOARD_FREQUENCY",
        GST_TURNOVER_BAND: "GST_ONBOARD_TURNOVER",
        GST_MULTI_GST_CHECK: "GST_ONBOARD_MULTI_CHECK",
        GST_MULTI_GST_ADD: "GST_ONBOARD_MULTI_ADD",
        GST_SEGMENT_DONE: "GST_ONBOARD_DONE",
        INSIGHTS_MENU: "INSIGHTS_MENU",
        ITR1_ASK_PAN: "ITR_ASK_PAN",
        ITR1_ASK_NAME: "ITR_ASK_NAME",
        ITR1_ASK_DOB: "ITR_ASK_DOB",
        ITR1_ASK_GENDER: "ITR_ASK_GENDER",
        ITR1_ASK_SALARY: "ITR_ASK_SALARY",
        ITR1_ASK_OTHER_INCOME: "ITR_ASK_OTHER_INCOME",
        ITR1_ASK_80C: "ITR_ASK_80C",
        ITR1_ASK_80D: "ITR_ASK_80D",
        ITR1_ASK_TDS: "ITR_ASK_TDS",
        ITR4_ASK_PAN: "ITR_ASK_PAN",
        ITR4_ASK_NAME: "ITR_ASK_NAME",
        ITR4_ASK_DOB: "ITR_ASK_DOB",
        ITR4_ASK_GENDER: "ITR_ASK_GENDER",
        ITR2_ASK_PAN: "ITR_ASK_PAN",
        ITR2_ASK_NAME: "ITR_ASK_NAME",
        ITR2_ASK_DOB: "ITR_ASK_DOB",
        ITR2_ASK_GENDER: "ITR_ASK_GENDER",
        ITR2_ASK_SALARY: "ITR_ASK_SALARY",
        ITR2_ASK_OTHER_INCOME: "ITR_ASK_OTHER_INCOME",
        ITR2_ASK_STCG: "ITR2_ASK_STCG",
        ITR2_ASK_LTCG: "ITR2_ASK_LTCG",
        ITR2_ASK_80C: "ITR_ASK_80C",
        ITR2_ASK_80D: "ITR_ASK_80D",
        ITR2_ASK_TDS: "ITR_ASK_TDS",
        ITR_ROUTE_ASK_CG: "ITR_ROUTE_ASK_CG",
        ITR_ROUTE_ASK_BIZ: "ITR_ROUTE_ASK_BIZ",
        ITR_ROUTE_RESULT: "ITR_ROUTE_DETECTED",
        ITR_ROUTE_CHOOSE_FORM: "ITR_ROUTE_CHOOSE_FORM",
        ITR4_ASK_TYPE: "ITR4_ASK_PROFESSION_TYPE",
        ITR4_ASK_TURNOVER: "ITR_ASK_TURNOVER",
        ITR4_ASK_80C: "ITR_ASK_80C",
        ITR4_ASK_TDS: "ITR_ASK_TDS",
        GST_FILING_MENU: "GST_FILING_MENU",
        GST_FILING_CONFIRM: "GST_FILING_CONFIRM",
        ITR_FILING_DOWNLOAD: "ITR_FILING_OPTIONS",
        ITR4_GST_LINK_CONFIRM: "ITR4_GST_DATA_FOUND",
        BATCH_UPLOAD: "UPLOAD_SMART_PROMPT",
        SMART_UPLOAD: "UPLOAD_SMART_PROMPT",
        NIL_FILING_MENU: "NIL_FILING_MENU",
        NIL_FILING_CONFIRM: "NIL_FILING_CONFIRM",
        SETTINGS_MENU: "SETTINGS_MENU",
        GST_PAYMENT_ENTRY: "GST_PAYMENT_PROMPT",
        GST_COMPOSITION_MENU: "GST_COMPOSITION_MENU",
        GST_QRMP_MENU: "GST_QRMP_MENU",
        GST_ANNUAL_MENU: "GST_ANNUAL_MENU",
        SEGMENT_ASK_TURNOVER: "SEGMENT_ASK_TURNOVER",
        SEGMENT_ASK_INVOICES: "SEGMENT_ASK_INVOICES",
        SEGMENT_ASK_EXPORT: "SEGMENT_ASK_EXPORT",
        SEGMENT_CONFIRM: "SEGMENT_DETECTED",
        # Phase 6: e-Invoice / e-WayBill
        EINVOICE_MENU: "EINVOICE_MENU",
        EINVOICE_UPLOAD: "EINVOICE_UPLOAD_PROMPT",
        EINVOICE_REVIEW: "EINVOICE_REVIEW",
        EINVOICE_STATUS_ASK: "EINVOICE_STATUS_PROMPT",
        EINVOICE_CANCEL: "EINVOICE_CANCEL_PROMPT",
        EWAYBILL_MENU: "EWAYBILL_MENU",
        EWAYBILL_UPLOAD: "EWAYBILL_UPLOAD_PROMPT",
        EWAYBILL_TRANSPORT: "EWAYBILL_TRANSPORT_ASK",
        EWAYBILL_TRACK_ASK: "EWAYBILL_TRACK_ASK",
        EWAYBILL_VEHICLE_ASK: "EWAYBILL_VEHICLE_ASK",
        # Phase 7: Wizard / Credit Check
        SMALL_WIZARD_SALES: "WIZARD_SALES_PROMPT",
        SMALL_WIZARD_PURCHASES: "WIZARD_PURCHASE_PROMPT",
        SMALL_WIZARD_SUMMARY: "WIZARD_SUMMARY",
        SMALL_WIZARD_CONFIRM: "WIZARD_CONFIRM",
        MEDIUM_CREDIT_CHECK: "CREDIT_CHECK_RUNNING",
        MEDIUM_CREDIT_RESULT: "CREDIT_CHECK_RESULT",
        GST_FILING_STATUS: "GST_FILING_STATUS",
        # Phase 8: Multi-GSTIN
        MULTI_GSTIN_MENU: "MULTI_GSTIN_MENU",
        MULTI_GSTIN_ADD: "MULTI_GSTIN_ADD_PROMPT",
        MULTI_GSTIN_LABEL: "MULTI_GSTIN_LABEL_PROMPT",
        MULTI_GSTIN_SUMMARY: "MULTI_GSTIN_SUMMARY",
        # Phase 9: Refund / Notice / Export
        REFUND_MENU: "REFUND_MENU",
        NOTICE_MENU: "NOTICE_MENU",
        EXPORT_MENU: "EXPORT_MENU",
        # Phase 10: Notification settings
        NOTIFICATION_SETTINGS: "NOTIFICATION_SETTINGS",
        # Phase 11: GST Sub-flows (upload / filing / payment)
        "GST_UPLOAD_MENU": "GST_UPLOAD_MENU",
        "GSTR2B_UPLOAD": "GSTR2B_UPLOAD_PROMPT",
        "GST_FILE_SELECT_PERIOD": "GST_FILE_SELECT_PERIOD",
        "GST_FILE_CHECKLIST": "GST_FILE_CHECKLIST",
        "GST_NIL_SUGGEST": "GST_NIL_SUGGEST",
        "GST_SUMMARY": "GST_SUMMARY",
        "GST_FILED_STATUS": "GST_FILED_STATUS",
        "GST_TAX_PAYABLE": "GST_TAX_PAYABLE",
        "GST_PAYMENT_CAPTURE": "GST_PAYMENT_CAPTURE",
        "GST_PAYMENT_CONFIRM": "GST_PAYMENT_CONFIRM",
        # Phase 12: Connect with CA
        "CONNECT_CA_ASK_TEXT": "CA_ASK_QUESTION_PROMPT",
        "CONNECT_CA_CALL_TIME": "CA_CALL_TIME_PROMPT",
        "CONNECT_CA_SHARE_DOCS": "CA_SHARE_DOCS_PROMPT",
        # Phase 13: Settings / Change Number
        "SETTINGS_PROFILE": "SETTINGS_PROFILE_DISPLAY",
        "SETTINGS_SEGMENT_VIEW": "SETTINGS_SEGMENT_DISPLAY",
        "CHANGE_NUMBER_START": "CHANGE_NUMBER_START",
        "CHANGE_NUMBER_CONFIRM_EMAIL": "CHANGE_NUMBER_ASK_EMAIL",
        "CHANGE_NUMBER_ENTER_OTP": "CHANGE_NUMBER_OTP_SENT",
        "CHANGE_NUMBER_SUCCESS": "CHANGE_NUMBER_SUCCESS",
        "CHANGE_NUMBER_LOCKED": "CHANGE_NUMBER_LOCKED",
        "CHANGE_NUMBER_CA_VERIFY": "CHANGE_NUMBER_CA_UPLOAD",
        "CHANGE_NUMBER_CA_PENDING": "CHANGE_NUMBER_CA_PENDING",
        # Session management
        "SESSION_RESUME_PROMPT": "SESSION_RESUME_PROMPT",
        "SENSITIVE_CONFIRM_EXPIRED": "SENSITIVE_CONFIRM_EXPIRED",
        "CONFIRM_SWITCH_MODULE": "CONFIRM_SWITCH_MODULE",
    }.get(state, "WELCOME_MENU")


# =========================
# NLP routing helper
# =========================
async def _handle_nlp_route(
    wa_id: str, session: Dict[str, Any], resolved, text: str
) -> bool:
    if resolved.method != "nlp" or resolved.target_state is None:
        return False

    lang = _get_lang(session)

    if resolved.target_state == "__POP__":
        session["state"] = pop_state(session)
        await session_cache.save_session(wa_id, session)
        await _send(wa_id, _t(session, _state_to_screen_key(session["state"])))
        return True

    if resolved.target_state == "WAIT_GSTIN" and resolved.extracted_entity:
        gstin = resolved.extracted_entity.upper()
        if is_valid_gstin(gstin):
            session.setdefault("data", {})["gstin"] = gstin
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await _send(wa_id, _t(session, "GST_SAVED", gstin=gstin))
            await _send(wa_id, _t(session, "WELCOME_MENU"))
            return True

    if resolved.target_state == "TAX_QA":
        push_state(session, session.get("state", MAIN_MENU))
        session["state"] = TAX_QA
        await session_cache.save_session(wa_id, session)
        intent_desc = get_intent_description("tax_qa", lang)
        await _send(wa_id, _t(session, "NLP_UNDERSTOOD", intent_desc=intent_desc))
        qa_history = session.get("data", {}).get("qa_history", [])
        answer = await _rag_tax_qa_answer(text, lang, qa_history)
        if answer:
            session.setdefault("data", {}).setdefault("qa_history", [])
            session["data"]["qa_history"].append({"role": "user", "content": text})
            session["data"]["qa_history"].append({"role": "assistant", "content": answer})
            if len(session["data"]["qa_history"]) > 20:
                session["data"]["qa_history"] = session["data"]["qa_history"][-10:]
            await session_cache.save_session(wa_id, session)
            await _send(wa_id, answer + "\n\nMENU = Main Menu\nBACK = Go Back")
        else:
            await _send(wa_id, _t(session, "TAX_QA_ERROR"))
        return True

    push_state(session, session.get("state", MAIN_MENU))
    session["state"] = resolved.target_state
    await session_cache.save_session(wa_id, session)
    if resolved.i18n_key:
        await _send(wa_id, _t(session, resolved.i18n_key))
    return True


# =========================
# PDF generation & send helper
# =========================
async def _send_invoice_pdf(wa_id: str, inv_dict: dict, session: dict) -> None:
    """Generate an invoice PDF and send it as a WhatsApp document."""
    try:
        pdf_bytes = generate_invoice_pdf(inv_dict)
        inv_no = inv_dict.get("invoice_number") or "invoice"
        filename = f"Invoice_{inv_no}.pdf"
        media_id = await upload_media(pdf_bytes, "application/pdf", filename)
        await send_whatsapp_document(
            wa_id, media_id, filename,
            caption=_t(session, "PDF_INVOICE_CAPTION"),
        )
    except Exception:
        logger.exception("Failed to send invoice PDF to %s", wa_id)


async def _send_batch_summary_pdf(
    wa_id: str, invoices: list[dict], session: dict
) -> None:
    """Generate a multi-invoice summary PDF and send it as a WhatsApp document."""
    try:
        pdf_bytes = generate_multi_invoice_summary_pdf(invoices)
        filename = f"Invoice_Summary_{len(invoices)}_items.pdf"
        media_id = await upload_media(pdf_bytes, "application/pdf", filename)
        await send_whatsapp_document(
            wa_id, media_id, filename,
            caption=_t(session, "PDF_BATCH_CAPTION", count=len(invoices)),
        )
    except Exception:
        logger.exception("Failed to send batch summary PDF to %s", wa_id)


# =========================
# GSTR-3B formatting
# =========================
def _format_gstr3b(summary) -> str:
    lines = [
        "--- GSTR-3B Summary ---",
        "",
        "Outward Taxable Supplies:",
        f"  Taxable Value: Rs {float(summary.outward_taxable_supplies.taxable_value):,.0f}",
        f"  IGST: Rs {float(summary.outward_taxable_supplies.igst):,.0f}",
        f"  CGST: Rs {float(summary.outward_taxable_supplies.cgst):,.0f}",
        f"  SGST: Rs {float(summary.outward_taxable_supplies.sgst):,.0f}",
        "",
        "ITC Eligible:",
        f"  IGST: Rs {float(summary.itc_eligible.igst):,.0f}",
        f"  CGST: Rs {float(summary.itc_eligible.cgst):,.0f}",
        f"  SGST: Rs {float(summary.itc_eligible.sgst):,.0f}",
        "",
    ]
    net_igst = float(summary.outward_taxable_supplies.igst - summary.itc_eligible.igst)
    net_cgst = float(summary.outward_taxable_supplies.cgst - summary.itc_eligible.cgst)
    net_sgst = float(summary.outward_taxable_supplies.sgst - summary.itc_eligible.sgst)
    lines.extend([
        "Net Tax Payable:",
        f"  IGST: Rs {net_igst:,.0f}",
        f"  CGST: Rs {net_cgst:,.0f}",
        f"  SGST: Rs {net_sgst:,.0f}",
        f"  TOTAL: Rs {net_igst + net_cgst + net_sgst:,.0f}",
    ])
    return "\n".join(lines)


# =========================
# ITR computation reconstruction helper
# =========================
async def _reconstruct_itr_computation(session: dict, form_type: str, input_type: str):
    """
    Reconstruct ITR input and computed result from session data.

    Returns (inp, result) tuple where inp is ITR1Input, ITR2Input, or ITR4Input
    and result is ITRResult.
    """
    if input_type == "documents":
        merged = dict_to_merged(
            session.get("data", {}).get("itr_docs", {}).get("merged", {})
        )
        if form_type == "ITR-1":
            inp = merged_to_itr1_input(merged)
            result = await compute_itr1(inp)
        elif form_type == "ITR-2":
            inp = merged_to_itr2_input(merged)
            result = await compute_itr2(inp)
        else:
            inp = merged_to_itr4_input(merged)
            result = await compute_itr4(inp)
    else:
        # Manual input
        if form_type == "ITR-1":
            d = session.get("data", {}).get("itr1", {})
            inp = ITR1Input(
                pan=d.get("pan", ""),
                name=d.get("name", ""),
                dob=d.get("dob", ""),
                gender=d.get("gender", ""),
                salary_income=Decimal(str(d.get("salary", 0))),
                other_income=Decimal(str(d.get("other_income", 0))),
                section_80c=Decimal(str(d.get("sec_80c", 0))),
                section_80d=Decimal(str(d.get("sec_80d", 0))),
                tds_total=Decimal(str(d.get("tds", 0))),
            )
            result = await compute_itr1(inp)
        elif form_type == "ITR-2":
            d = session.get("data", {}).get("itr2", {})
            inp = ITR2Input(
                pan=d.get("pan", ""),
                name=d.get("name", ""),
                dob=d.get("dob", ""),
                gender=d.get("gender", ""),
                salary_income=Decimal(str(d.get("salary", 0))),
                other_income=Decimal(str(d.get("other_income", 0))),
                stcg_111a=Decimal(str(d.get("stcg_111a", 0))),
                ltcg_112a=Decimal(str(d.get("ltcg_112a", 0))),
                section_80c=Decimal(str(d.get("sec_80c", 0))),
                section_80d=Decimal(str(d.get("sec_80d", 0))),
                tds_total=Decimal(str(d.get("tds", 0))),
            )
            result = await compute_itr2(inp)
        else:
            d = session.get("data", {}).get("itr4", {})
            is_biz = d.get("type") == "business"
            inp = ITR4Input(
                pan=d.get("pan", ""),
                name=d.get("name", ""),
                dob=d.get("dob", ""),
                gender=d.get("gender", ""),
                gross_turnover=Decimal(str(d.get("turnover", 0))) if is_biz else Decimal("0"),
                presumptive_rate=Decimal(str(d.get("rate", 8))) if is_biz else Decimal("8"),
                gross_receipts=Decimal(str(d.get("turnover", 0))) if not is_biz else Decimal("0"),
                professional_rate=Decimal(str(d.get("rate", 50))) if not is_biz else Decimal("50"),
                section_80c=Decimal(str(d.get("sec_80c", 0))),
                tds_total=Decimal(str(d.get("tds", 0))),
            )
            result = await compute_itr4(inp)
    return inp, result


# ==========================================================
# WEBHOOK VERIFY (GET)
# ==========================================================
@router.get("/webhook")
async def verify(request: Request):
    q = request.query_params
    if (
        q.get("hub.mode") == "subscribe"
        and q.get("hub.verify_token") == settings.WHATSAPP_VERIFY_TOKEN
    ):
        return Response(content=q.get("hub.challenge"))
    return Response(status_code=403)


# ==========================================================
# WEBHOOK INBOUND (POST)
# ==========================================================
@router.post("/webhook")
async def inbound(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_webhook_signature(body, signature):
        logger.warning("Invalid webhook signature — rejecting request")
        return Response(status_code=403)

    payload = json.loads(body)
    logger.info("Inbound WhatsApp payload: %s", payload)

    try:
        value = payload["entry"][0]["changes"][0]["value"]

        if "statuses" in value:
            return Response(status_code=200)

        msg = value["messages"][0]
        wa_id = msg["from"]

        session = await session_cache.get_session(wa_id)
        state = session.get("state", MAIN_MENU)
        lang = _get_lang(session)
        text = ""

        # =====================================================
        # AUDIO / VOICE HANDLING
        # =====================================================
        if msg["type"] == "audio":
            audio_media = msg["audio"]
            media_id = audio_media.get("id")
            if not media_id:
                await _send(wa_id, _t(session, "VOICE_ERROR"))
                return Response(status_code=200)
            await _send(wa_id, _t(session, "VOICE_PROCESSING"))
            voice_result = await process_voice_message(media_id, lang)
            if voice_result.error:
                key = "VOICE_NOT_CONFIGURED" if voice_result.error == "stt_not_configured" else "VOICE_ERROR"
                await _send(wa_id, _t(session, key))
                return Response(status_code=200)
            transcribed = voice_result.transcribed_text
            await _send(wa_id, _t(session, "VOICE_UNDERSTOOD", transcribed=transcribed))
            session.setdefault("data", {})["last_voice_text"] = transcribed
            text = transcribed

        # =====================================================
        # TEXT MESSAGE
        # =====================================================
        if msg["type"] == "text":
            text = msg["text"]["body"].strip()

        # =====================================================
        # INTERACTIVE MESSAGE (button / list replies)
        # =====================================================
        if msg["type"] == "interactive":
            interactive = msg.get("interactive", {})
            if "button_reply" in interactive:
                text = interactive["button_reply"]["id"]
            elif "list_reply" in interactive:
                text = interactive["list_reply"]["id"]

        # =====================================================
        # PROCESS TEXT (typed, transcribed, or interactive reply)
        # =====================================================
        if text:
            # === universal nav ===
            # States that expect free-form input — global commands are NOT
            # intercepted here (the typed text IS valid data).
            _FREE_INPUT_STATES = {
                # Personal details (PAN, name, DOB — free text)
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

            # --- Update session activity timestamp on every inbound text ---
            from app.infrastructure.cache.session_cache import touch_session
            touch_session(session)

            # --- Soft-expiry check: idle > 30 min → resume prompt ---
            from app.infrastructure.cache.session_cache import is_soft_expired
            if is_soft_expired(session) and state not in (CHOOSE_LANG, MAIN_MENU, "SESSION_RESUME_PROMPT", "RESTART_CONFIRM"):
                session["data"]["pre_expiry_state"] = state
                session["state"] = "SESSION_RESUME_PROMPT"
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, _t(session, "SESSION_RESUME_PROMPT"))
                return Response(status_code=200)

            # Normalize for command matching
            text_upper = text.strip().upper()

            # === MENU — return to main menu from any state ===
            if text_upper == "MENU" and state not in _FREE_INPUT_STATES:
                await show_main_menu(wa_id, session)
                return Response(status_code=200)

            # === BACK — go to previous screen ===
            if text_upper == "BACK" and state not in _FREE_INPUT_STATES:
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, _t(session, _state_to_screen_key(session["state"])))
                return Response(status_code=200)

            # === HELP — show available commands from any state ===
            if text_upper == "HELP":
                await _send(wa_id, _t(session, "HELP_TEXT"))
                return Response(status_code=200)

            # === RESTART — two-step: prompt confirmation first ===
            if text_upper == "RESTART":
                if state == "RESTART_CONFIRM":
                    # User already saw prompt and typed RESTART again → confirm
                    await session_cache.clear_session(wa_id)
                    from app.infrastructure.cache.session_cache import _default_session
                    new_session = _default_session()
                    new_session["lang"] = session.get("lang", "en")
                    await session_cache.save_session(wa_id, new_session)
                    await _send(wa_id, _t(new_session, "RESTART_CONFIRMED"))
                    await show_main_menu(wa_id, new_session)
                    return Response(status_code=200)
                else:
                    # First time — ask for confirmation
                    session["data"]["pre_restart_state"] = state
                    session["state"] = "RESTART_CONFIRM"
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "RESTART_CONFIRM"))
                    return Response(status_code=200)

            # If user was at RESTART_CONFIRM but typed something else, go back
            if state == "RESTART_CONFIRM":
                prev = session.get("data", {}).pop("pre_restart_state", MAIN_MENU)
                session["state"] = prev
                await session_cache.save_session(wa_id, session)
                # Fall through to normal state processing

            # === NLP INTENT DETECTION ===
            resolved = await resolve_intent(text, lang, state)
            if resolved.method == "nlp":
                handled = await _handle_nlp_route(wa_id, session, resolved, text)
                if handled:
                    return Response(status_code=200)

            # === STATE-BASED ROUTING ===

            # --- TAX Q&A ---
            if state == TAX_QA:
                qa_history = session.get("data", {}).get("qa_history", [])
                answer = await _rag_tax_qa_answer(text, lang, qa_history)
                if answer:
                    session.setdefault("data", {}).setdefault("qa_history", [])
                    session["data"]["qa_history"].append({"role": "user", "content": text})
                    session["data"]["qa_history"].append({"role": "assistant", "content": answer})
                    if len(session["data"]["qa_history"]) > 20:
                        session["data"]["qa_history"] = session["data"]["qa_history"][-10:]
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, answer + "\n\nMENU = Main Menu\nBACK = Go Back")
                else:
                    await _send(wa_id, _t(session, "TAX_QA_ERROR"))
                return Response(status_code=200)

            # --- CHOOSE LANG (first-time user intro) ---
            if state == CHOOSE_LANG:
                if text in LANG_NUMBER_MAP:
                    session["lang"] = LANG_NUMBER_MAP[text]
                    lang_name = LANG_NAMES[_get_lang(session)]
                    await _send(wa_id, _t(session, "LANG_SET", lang_name=lang_name))
                    # Proceed to segment questions
                    session["state"] = SEGMENT_ASK_TURNOVER
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "SEGMENT_ASK_TURNOVER"))
                else:
                    await _send(wa_id, _t(session, "CHOOSE_LANG"))
                return Response(status_code=200)

            # --- MAIN MENU ---
            if state == MAIN_MENU:
                if text == "1":
                    push_state(session, MAIN_MENU)
                    # Check if user has completed GST onboarding
                    if session.get("data", {}).get("gst_onboarded"):
                        session["state"] = GST_MENU
                        # Build dynamic GST menu based on client segment
                        try:
                            from app.core.db import get_db as _get_db
                            from app.domain.services.whatsapp_menu_builder import build_gst_menu
                            async for _db in _get_db():
                                menu_result = await build_gst_menu(wa_id, session, _db)
                                break
                        except Exception:
                            menu_result = _t(session, "GST_SERVICES")
                        await session_cache.save_session(wa_id, session)
                        await _send_menu_result(wa_id, menu_result)
                    else:
                        # Not yet onboarded — route to GST onboarding
                        session["state"] = GST_START_GSTIN
                        await session_cache.save_session(wa_id, session)
                        await _send(wa_id, _t(session, "GST_ONBOARD_ASK_GSTIN"))
                    return Response(status_code=200)
                if text == "2":
                    push_state(session, MAIN_MENU)
                    session["state"] = ITR_MENU
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "ITR_SERVICES"))
                    return Response(status_code=200)
                if text == "3":
                    push_state(session, MAIN_MENU)
                    session["state"] = CONNECT_CA_MENU
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "CONNECT_CA_MENU"))
                    return Response(status_code=200)
                if text == "4":
                    push_state(session, MAIN_MENU)
                    session["state"] = SETTINGS_MENU
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "SETTINGS_MENU"))
                    return Response(status_code=200)
                # Unrecognised text in main menu → re-show the welcome menu
                await show_main_menu(wa_id, session)
                return Response(status_code=200)

            # --- ITR MENU and ITR filing flows (ITR-1, ITR-2, ITR-4, smart routing) ---
            # Extracted to wa_handlers/itr_filing_flow.py


            # === ITR DOCUMENT UPLOAD FLOW ===
            # States: ITR_DOC_TYPE_MENU, ITR_DOC_UPLOAD, ITR_DOC_REVIEW,
            #         ITR_DOC_EDIT_FIELD, ITR_DOC_PICK_ITR
            # Extracted to: app/api/routes/wa_handlers/itr_doc_upload.py

            # --- GST MENU (dynamic dispatch via segment gating) ---
            # Handled by wa_handlers/gst_compliance.py

            # --- SEGMENT ONBOARDING FLOW ---
            if state == SEGMENT_ASK_TURNOVER:
                turnover_map = {"1": 0, "2": 25_00_00_000, "3": 75_00_00_000, "4": 0}
                if text in turnover_map:
                    session.setdefault("data", {})["seg_turnover"] = turnover_map[text]
                    session["state"] = SEGMENT_ASK_INVOICES
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "SEGMENT_ASK_INVOICES"))
                else:
                    await _send(wa_id, _t(session, "SEGMENT_ASK_TURNOVER"))
                return Response(status_code=200)

            if state == SEGMENT_ASK_INVOICES:
                invoice_map = {"1": 25, "2": 75, "3": 300, "4": 600, "5": 0}
                if text in invoice_map:
                    session.setdefault("data", {})["seg_invoices"] = invoice_map[text]
                    session["state"] = SEGMENT_ASK_EXPORT
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "SEGMENT_ASK_EXPORT"))
                else:
                    await _send(wa_id, _t(session, "SEGMENT_ASK_INVOICES"))
                return Response(status_code=200)

            if state == SEGMENT_ASK_EXPORT:
                export_map = {"1": True, "2": False, "3": False}
                if text in export_map:
                    session.setdefault("data", {})["seg_export"] = export_map[text]

                    # Auto-detect segment
                    from app.domain.services.segment_detection import detect_segment
                    seg_data = session.get("data", {})
                    detected = detect_segment(
                        annual_turnover=seg_data.get("seg_turnover", 0),
                        monthly_invoice_volume=seg_data.get("seg_invoices", 0),
                        is_exporter=seg_data.get("seg_export", False),
                    )
                    session["data"]["detected_segment"] = detected

                    # Build features summary
                    segment_label = _t(session, f"SEGMENT_LABEL_{detected}")
                    try:
                        from app.core.db import get_db as _get_db
                        from app.domain.services.feature_registry import get_features_for_segment
                        async for _db in _get_db():
                            features = await get_features_for_segment(detected, _db)
                            break
                        features_summary = "\n".join(
                            f"- {f['name']}" for f in features
                        )
                    except Exception:
                        features_summary = "(features will be configured)"

                    session["state"] = SEGMENT_CONFIRM
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "SEGMENT_DETECTED",
                                          segment_label=segment_label,
                                          features_summary=features_summary))
                else:
                    await _send(wa_id, _t(session, "SEGMENT_ASK_EXPORT"))
                return Response(status_code=200)

            if state == SEGMENT_CONFIRM:
                if text == "1":
                    # Accept detected segment — update DB and proceed to GST menu
                    detected = session.get("data", {}).get("detected_segment", "small")
                    gstin = session.get("data", {}).get("gstin")
                    if gstin:
                        try:
                            from app.core.db import get_db as _get_db
                            from app.infrastructure.db.models import BusinessClient as BCModel
                            from sqlalchemy import select as sa_select
                            async for _db in _get_db():
                                bc_stmt = sa_select(BCModel).where(BCModel.gstin == gstin)
                                bc_result = await _db.execute(bc_stmt)
                                bc = bc_result.scalar_one_or_none()
                                if bc:
                                    bc.segment = detected
                                    seg_data = session.get("data", {})
                                    bc.annual_turnover = seg_data.get("seg_turnover")
                                    bc.monthly_invoice_volume = seg_data.get("seg_invoices")
                                    bc.is_exporter = seg_data.get("seg_export", False)
                                    await _db.commit()
                                    # Invalidate feature cache
                                    from app.domain.services.feature_registry import invalidate_feature_cache
                                    await invalidate_feature_cache(bc.id)
                                break
                        except Exception:
                            logger.exception("Failed to save segment for gstin=%s", gstin)

                    session["data"]["segment_done"] = True
                    session["data"]["client_segment"] = detected
                    # Clean up segment onboarding data
                    for key in ("seg_turnover", "seg_invoices", "seg_export", "detected_segment"):
                        session.get("data", {}).pop(key, None)

                    # If came from intro flow (no GST onboarding yet), go to main menu
                    if not session.get("data", {}).get("gst_onboarded"):
                        await show_main_menu(wa_id, session)
                        return Response(status_code=200)

                    # Otherwise resume to GST menu
                    session["state"] = GST_MENU
                    try:
                        from app.core.db import get_db as _get_db
                        from app.domain.services.whatsapp_menu_builder import build_gst_menu
                        async for _db in _get_db():
                            menu_result = await build_gst_menu(wa_id, session, _db)
                            break
                    except Exception:
                        menu_result = _t(session, "GST_SERVICES")
                    await session_cache.save_session(wa_id, session)
                    await _send_menu_result(wa_id, menu_result)
                    return Response(status_code=200)
                elif text == "2":
                    # Re-start segment onboarding
                    session["state"] = SEGMENT_ASK_TURNOVER
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "SEGMENT_ASK_TURNOVER"))
                    return Response(status_code=200)
                else:
                    await _send(wa_id, _t(session, "SEGMENT_DETECTED",
                                          segment_label="",
                                          features_summary="Reply 1 to continue or 2 to change."))
                    return Response(status_code=200)

            # ===================================================
            # PHASE 6–10: Modular handler dispatch
            # Each handler module handles a set of states and
            # returns Response if handled, None otherwise.
            # ===================================================
            from app.api.routes.wa_handlers import HANDLER_CHAIN as _wa_handler_chain
            _handler_kwargs = dict(
                session_cache=session_cache,
                send=_send,
                send_buttons=_send_buttons,
                send_menu_result=_send_menu_result,
                t=_t,
                push_state=push_state,
                pop_state=pop_state,
                state_to_screen_key=_state_to_screen_key,
                get_lang=_get_lang,
            )
            for _handler_mod in _wa_handler_chain:
                _handler_result = await _handler_mod.handle(
                    state, text, wa_id, session, **_handler_kwargs
                )
                if _handler_result is not None:
                    return _handler_result

            # ===================================================
            # PHASE 6: e-Invoice Conversational Flow (inline fallback)
            # ===================================================
            if state == EINVOICE_MENU:
                if text in ("einv_generate", "1"):
                    # Ask user to upload invoice
                    session["state"] = EINVOICE_UPLOAD
                    session.setdefault("data", {})["einvoice_invoices"] = []
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "EINVOICE_UPLOAD_PROMPT"))
                    return Response(status_code=200)
                elif text in ("einv_status", "2"):
                    session["state"] = EINVOICE_STATUS_ASK
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "EINVOICE_STATUS_PROMPT"))
                    return Response(status_code=200)
                elif text in ("einv_cancel", "3"):
                    session["state"] = EINVOICE_CANCEL
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "EINVOICE_CANCEL_PROMPT"))
                    return Response(status_code=200)
                else:
                    await _send(wa_id, _t(session, "EINVOICE_MENU"))
                    return Response(status_code=200)

            if state == EINVOICE_UPLOAD:
                if text.lower() == "done":
                    einv_invoices = session.get("data", {}).get("einvoice_invoices", [])
                    if not einv_invoices:
                        await _send(wa_id, "No invoices uploaded yet. Please upload an invoice image/PDF or type 'done' to go back.")
                        return Response(status_code=200)
                    # Show review
                    lines = ["🧾 *Invoice Review*\n"]
                    for i, inv in enumerate(einv_invoices, 1):
                        lines.append(f"{i}) Inv #{inv.get('invoice_number', '?')} — ₹{inv.get('total_amount', 0):,.2f}")
                    lines.append(f"\nTotal: {len(einv_invoices)} invoice(s)")
                    lines.append("\nGenerate IRN for all? Reply 1=Yes, 2=Cancel")
                    session["state"] = EINVOICE_CONFIRM
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, "\n".join(lines))
                    return Response(status_code=200)
                # Image/document upload handled by the invoice parsing pipeline below
                # For text: could be a manual invoice number entry — stay in state
                await _send(wa_id, "Upload your invoice (photo/PDF), or type 'done' when finished.")
                return Response(status_code=200)

            if state == EINVOICE_CONFIRM:
                if text == "1":
                    # Generate IRN for all
                    gstin = session.get("data", {}).get("gstin", "")
                    einv_invoices = session.get("data", {}).get("einvoice_invoices", [])
                    await _send(wa_id, _t(session, "EINVOICE_GENERATING"))
                    from app.domain.services.einvoice_flow import generate_irn_for_invoice
                    results = []
                    for inv in einv_invoices:
                        result = await generate_irn_for_invoice(gstin, inv)
                        if result["success"]:
                            results.append(f"✅ Inv #{inv.get('invoice_number', '?')}: IRN={result['irn']}")
                        else:
                            results.append(f"❌ Inv #{inv.get('invoice_number', '?')}: {result['error']}")
                    msg = "\n".join(results)
                    await _send(wa_id, _t(session, "EINVOICE_IRN_SUCCESS", result_message=msg))
                    session["state"] = GST_MENU
                    session.get("data", {}).pop("einvoice_invoices", None)
                    await session_cache.save_session(wa_id, session)
                else:
                    session["state"] = GST_MENU
                    session.get("data", {}).pop("einvoice_invoices", None)
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, "Cancelled. Returning to GST menu.")
                    try:
                        from app.core.db import get_db as _get_db
                        from app.domain.services.whatsapp_menu_builder import build_gst_menu
                        async for _db in _get_db():
                            menu_result = await build_gst_menu(wa_id, session, _db)
                            break
                    except Exception:
                        menu_result = _t(session, "GST_SERVICES")
                    await _send_menu_result(wa_id, menu_result)
                return Response(status_code=200)

            if state == EINVOICE_STATUS_ASK:
                # User provides IRN number to check status
                irn = text.strip()
                gstin = session.get("data", {}).get("gstin", "")
                from app.domain.services.einvoice_flow import get_irn_status
                result = await get_irn_status(gstin, irn)
                if result["success"]:
                    await _send(wa_id, f"📋 IRN Status: {result['status']}\n\nMENU = Main Menu\nBACK = Go Back")
                else:
                    await _send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            if state == EINVOICE_CANCEL:
                # User provides IRN to cancel
                irn = text.strip()
                gstin = session.get("data", {}).get("gstin", "")
                from app.domain.services.einvoice_flow import cancel_irn
                result = await cancel_irn(gstin, irn)
                if result["success"]:
                    await _send(wa_id, _t(session, "EINVOICE_CANCEL_SUCCESS", irn=irn))
                else:
                    await _send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            # ===================================================
            # PHASE 6: e-WayBill Conversational Flow
            # ===================================================
            if state == EWAYBILL_MENU:
                if text in ("ewb_generate", "1"):
                    session["state"] = EWAYBILL_UPLOAD
                    session.setdefault("data", {})["ewaybill_invoices"] = []
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "EWAYBILL_UPLOAD_PROMPT"))
                    return Response(status_code=200)
                elif text in ("ewb_track", "2"):
                    session["state"] = EWAYBILL_TRACK_ASK
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "EWAYBILL_TRACK_ASK"))
                    return Response(status_code=200)
                elif text in ("ewb_vehicle", "3"):
                    session["state"] = EWAYBILL_VEHICLE_ASK
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "EWAYBILL_VEHICLE_ASK"))
                    return Response(status_code=200)
                else:
                    await _send(wa_id, _t(session, "EWAYBILL_MENU"))
                    return Response(status_code=200)

            if state == EWAYBILL_UPLOAD:
                if text.lower() == "done":
                    ewb_invoices = session.get("data", {}).get("ewaybill_invoices", [])
                    if not ewb_invoices:
                        await _send(wa_id, "No invoices uploaded yet. Please upload an invoice or type 'done' to go back.")
                        return Response(status_code=200)
                    # Ask for transport details
                    session["state"] = EWAYBILL_TRANSPORT
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "EWAYBILL_TRANSPORT_ASK"))
                    return Response(status_code=200)
                await _send(wa_id, "Upload your invoice (photo/PDF), or type 'done' when finished.")
                return Response(status_code=200)

            if state == EWAYBILL_TRANSPORT:
                # Parse transport details: "vehicle_no, mode, distance"
                parts = [p.strip() for p in text.split(",")]
                transport = {
                    "vehicle_no": parts[0] if len(parts) > 0 else "",
                    "mode": parts[1] if len(parts) > 1 else "Road",
                    "distance": parts[2] if len(parts) > 2 else "0",
                }
                session.setdefault("data", {})["ewb_transport"] = transport
                # Generate e-WayBill
                gstin = session.get("data", {}).get("gstin", "")
                ewb_invoices = session.get("data", {}).get("ewaybill_invoices", [])
                await _send(wa_id, _t(session, "EWAYBILL_GENERATING"))
                from app.domain.services.ewaybill_flow import generate_ewb
                results = []
                for inv in ewb_invoices:
                    result = await generate_ewb(gstin, inv, transport)
                    if result["success"]:
                        results.append(f"✅ Inv #{inv.get('invoice_number', '?')}: EWB={result['ewb_no']}")
                    else:
                        results.append(f"❌ Inv #{inv.get('invoice_number', '?')}: {result['error']}")
                msg = "\n".join(results)
                await _send(wa_id, _t(session, "EWAYBILL_SUCCESS", result_message=msg))
                session["state"] = GST_MENU
                session.get("data", {}).pop("ewaybill_invoices", None)
                session.get("data", {}).pop("ewb_transport", None)
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            if state == EWAYBILL_TRACK_ASK:
                ewb_no = text.strip()
                gstin = session.get("data", {}).get("gstin", "")
                from app.domain.services.ewaybill_flow import track_ewb
                result = await track_ewb(gstin, ewb_no)
                if result["success"]:
                    await _send(wa_id, _t(session, "EWAYBILL_TRACK_RESULT",
                                          ewb_no=ewb_no,
                                          status=result["status"],
                                          valid_upto=result.get("valid_upto", "N/A")))
                else:
                    await _send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            if state == EWAYBILL_VEHICLE_ASK:
                # Format: "EWB_NO, NEW_VEHICLE, REASON"
                parts = [p.strip() for p in text.split(",")]
                ewb_no = parts[0] if len(parts) > 0 else ""
                vehicle_no = parts[1] if len(parts) > 1 else ""
                reason = parts[2] if len(parts) > 2 else "Vehicle breakdown"
                gstin = session.get("data", {}).get("gstin", "")
                from app.domain.services.ewaybill_flow import update_vehicle
                result = await update_vehicle(gstin, ewb_no, vehicle_no, reason)
                if result["success"]:
                    await _send(wa_id, f"✅ Vehicle updated for EWB {ewb_no}\nNew Vehicle: {vehicle_no}\n\nMENU = Main Menu\nBACK = Go Back")
                else:
                    await _send(wa_id, f"❌ {result['error']}\n\nMENU = Main Menu\nBACK = Go Back")
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            # ===================================================
            # PHASE 7: Small Segment Wizard
            # ===================================================
            if state == SMALL_WIZARD_SALES:
                if text.lower() == "done":
                    sales = session.get("data", {}).get("wizard_sales_invoices", [])
                    from app.domain.services.gst_explainer import compute_sales_tax, detect_nil_return
                    if detect_nil_return(sales):
                        await _send(wa_id, _t(session, "WIZARD_NIL_DETECT"))
                        session["state"] = GST_MENU
                        await session_cache.save_session(wa_id, session)
                        return Response(status_code=200)
                    sales_tax = compute_sales_tax(sales)
                    await _send(wa_id, _t(session, "WIZARD_SALES_DONE", sales_tax=f"₹{sales_tax:,.2f}", count=len(sales)))
                    session["state"] = SMALL_WIZARD_PURCHASES
                    session.setdefault("data", {})["wizard_purchase_invoices"] = []
                    session["data"]["wizard_sales_tax"] = sales_tax
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "WIZARD_PURCHASE_PROMPT"))
                    return Response(status_code=200)
                # Image/document handled below in invoice parsing
                await _send(wa_id, "📸 Upload sales bills (photos/PDFs). Send 'done' when finished.")
                return Response(status_code=200)

            if state == SMALL_WIZARD_PURCHASES:
                if text.lower() == "done":
                    purchases = session.get("data", {}).get("wizard_purchase_invoices", [])
                    from app.domain.services.gst_explainer import (
                        compute_purchase_credit, format_simple_summary
                    )
                    sales = session.get("data", {}).get("wizard_sales_invoices", [])
                    lang = _get_lang(session)
                    segment = session.get("data", {}).get("client_segment", "small")
                    summary = format_simple_summary(sales, purchases, lang, segment)
                    session["state"] = SMALL_WIZARD_CONFIRM
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, summary)
                    await _send_buttons(
                        wa_id,
                        _t(session, "WIZARD_CONFIRM"),
                        [
                            {"id": "wiz_send_ca", "title": "✅ Send to CA"},
                            {"id": "wiz_edit", "title": "📝 Make Changes"},
                            {"id": "wiz_cancel", "title": "❌ Cancel"},
                        ],
                    )
                    return Response(status_code=200)
                await _send(wa_id, "📸 Upload purchase bills for credit. Send 'done' when finished.")
                return Response(status_code=200)

            if state == SMALL_WIZARD_CONFIRM:
                if text in ("wiz_send_ca", "1"):
                    await _send(wa_id, _t(session, "WIZARD_SENT_TO_CA"))
                    session["state"] = GST_MENU
                    for k in ("wizard_sales_invoices", "wizard_purchase_invoices", "wizard_sales_tax"):
                        session.get("data", {}).pop(k, None)
                    await session_cache.save_session(wa_id, session)
                elif text in ("wiz_edit", "2"):
                    session["state"] = SMALL_WIZARD_SALES
                    session.setdefault("data", {})["wizard_sales_invoices"] = []
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "WIZARD_SALES_PROMPT"))
                else:
                    session["state"] = GST_MENU
                    for k in ("wizard_sales_invoices", "wizard_purchase_invoices", "wizard_sales_tax"):
                        session.get("data", {}).pop(k, None)
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, "Cancelled. Returning to GST menu.\n\nMENU = Main Menu")
                return Response(status_code=200)

            # ===================================================
            # PHASE 7: Medium Credit Check
            # ===================================================
            if state == MEDIUM_CREDIT_CHECK:
                # Auto-run credit check: import GSTR-2B + reconcile
                gstin = session.get("data", {}).get("gstin", "")
                period = session.get("data", {}).get("period") or get_current_gst_period()
                await _send(wa_id, "🔄 Running credit check... Importing purchase data and matching invoices.")
                matched = 0
                mismatched = 0
                additional_credit = "₹0"
                try:
                    from app.core.db import get_db as _get_db
                    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
                    from sqlalchemy import select as sa_select
                    from app.infrastructure.db.models import User as UserModel

                    async for db in _get_db():
                        user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                        user_result = await db.execute(user_stmt)
                        user = user_result.scalar_one_or_none()
                        if user:
                            rp_repo = ReturnPeriodRepository(db)
                            rp = await rp_repo.create_or_get(user.id, gstin, period)

                            # Step 1: Import GSTR-2B
                            from app.domain.services.gstr2b_service import import_gstr2b
                            import_result = await import_gstr2b(
                                user_id=user.id, gstin=gstin,
                                period=period, period_id=rp.id, db=db,
                            )

                            # Step 2: Run reconciliation
                            from app.domain.services.gst_reconciliation import reconcile_period
                            summary = await reconcile_period(rp.id, db)

                            matched = summary.matched
                            mismatched = summary.value_mismatch + summary.missing_in_2b + summary.missing_in_books
                            # Additional credit = invoices in 2B but not in books (missing_in_books)
                            additional_credit = f"₹{summary.missing_in_books_taxable:,.2f}"

                            # Store in session for later reference
                            session.setdefault("data", {})["credit_check"] = {
                                "matched": matched,
                                "mismatched": mismatched,
                                "value_mismatch": summary.value_mismatch,
                                "missing_in_2b": summary.missing_in_2b,
                                "missing_in_books": summary.missing_in_books,
                                "additional_credit": str(summary.missing_in_books_taxable),
                                "period_id": str(rp.id),
                            }
                        else:
                            logger.warning("Credit check: user not found for %s", wa_id)
                except Exception as e:
                    logger.exception("Credit check failed for %s", wa_id)
                    await _send(wa_id, f"⚠️ Credit check encountered an issue: {str(e)[:100]}. Showing available data.")

                session["state"] = MEDIUM_CREDIT_RESULT
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, _t(session, "CREDIT_CHECK_RESULT",
                                      matched=matched, mismatched=mismatched,
                                      additional_credit=additional_credit))
                return Response(status_code=200)

            if state == MEDIUM_CREDIT_RESULT:
                if text == "1":
                    # Continue to filing
                    session["state"] = GST_PERIOD_MENU
                    await session_cache.save_session(wa_id, session)
                    gstin = session.get("data", {}).get("gstin", "")
                    period = session.get("data", {}).get("period") or get_current_gst_period()
                    await _send(wa_id, _t(session, "GST_PERIOD_MENU", period=period, gstin=gstin, status="draft"))
                elif text == "2":
                    # View mismatches — read from session credit_check data
                    cc = session.get("data", {}).get("credit_check", {})
                    val_mm = cc.get("value_mismatch", 0)
                    miss_2b = cc.get("missing_in_2b", 0)
                    miss_books = cc.get("missing_in_books", 0)
                    lines = ["📊 *Mismatch Details:*\n"]
                    if val_mm:
                        lines.append(f"⚠️ Value mismatches: {val_mm} invoice(s)")
                    if miss_2b:
                        lines.append(f"📤 Missing in GSTR-2B (not from suppliers): {miss_2b} invoice(s)")
                    if miss_books:
                        lines.append(f"📥 In GSTR-2B but not in your books: {miss_books} invoice(s)")
                    if not (val_mm or miss_2b or miss_books):
                        lines.append("✅ No mismatches found — all invoices matched!")
                    lines.append("\n1) Continue to filing\nMENU = Main Menu\nBACK = Go Back")
                    await _send(wa_id, "\n".join(lines))
                elif text == "3":
                    # Notify suppliers about missing bills
                    miss_2b = session.get("data", {}).get("credit_check", {}).get("missing_in_2b", 0)
                    if miss_2b:
                        await _send(wa_id, f"📨 Supplier notification for {miss_2b} missing invoice(s) will be sent. This feature requires email/WhatsApp integration with your suppliers.\n\nMENU = Main Menu\nBACK = Go Back")
                    else:
                        await _send(wa_id, "✅ No missing invoices to notify suppliers about.\n\nMENU = Main Menu\nBACK = Go Back")
                else:
                    session["state"] = pop_state(session)
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, _state_to_screen_key(session["state"])))
                return Response(status_code=200)

            # ===================================================
            # PHASE 7: Filing Status
            # ===================================================
            if state == GST_FILING_STATUS:
                # Any input returns to previous state
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, _t(session, _state_to_screen_key(session["state"])))
                return Response(status_code=200)

            # ===================================================
            # PHASE 8: Multi-GSTIN Management
            # ===================================================
            if state == MULTI_GSTIN_MENU:
                if text == "1":
                    # Add GSTIN
                    session["state"] = MULTI_GSTIN_ADD
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "MULTI_GSTIN_ADD_PROMPT"))
                    return Response(status_code=200)
                elif text == "2":
                    # Switch GSTIN
                    await _send(wa_id, "Enter the GSTIN number to switch to:")
                    return Response(status_code=200)
                elif text == "3":
                    # Summary
                    session["state"] = MULTI_GSTIN_SUMMARY
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "MULTI_GSTIN_SUMMARY"))
                    return Response(status_code=200)
                else:
                    await _send(wa_id, _t(session, "MULTI_GSTIN_MENU"))
                    return Response(status_code=200)

            if state == MULTI_GSTIN_ADD:
                new_gstin = text.strip().upper()
                if is_valid_gstin(new_gstin):
                    session.setdefault("data", {})["pending_gstin"] = new_gstin
                    session["state"] = MULTI_GSTIN_LABEL
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "MULTI_GSTIN_LABEL_PROMPT"))
                else:
                    await _send(wa_id, "Invalid GSTIN format. Please enter a valid 15-character GSTIN:")
                return Response(status_code=200)

            if state == MULTI_GSTIN_LABEL:
                label = text.strip()
                new_gstin = session.get("data", {}).get("pending_gstin", "")
                from app.domain.services.multi_gstin_service import add_gstin
                try:
                    from app.core.db import get_db as _get_db
                    from app.infrastructure.db.models import User
                    from sqlalchemy import select as _sa_select
                    async for _db in _get_db():
                        # Look up real user_id from WhatsApp number
                        _user_stmt = _sa_select(User.id).where(User.whatsapp_number == wa_id)
                        _user_result = await _db.execute(_user_stmt)
                        _user_row = _user_result.scalar_one_or_none()
                        if _user_row:
                            result = await add_gstin(_user_row, new_gstin, label, _db)
                        else:
                            result = {"success": False, "error": "User not found"}
                        if result["success"]:
                            await _send(wa_id, _t(session, "MULTI_GSTIN_ADDED", gstin=new_gstin, label=label))
                        else:
                            await _send(wa_id, f"❌ {result['error']}")
                        break
                except Exception:
                    logger.exception("Multi-GSTIN add error")
                    await _send(wa_id, "Error adding GSTIN. Please try again.")
                session["state"] = MULTI_GSTIN_MENU
                session.get("data", {}).pop("pending_gstin", None)
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            if state == MULTI_GSTIN_SUMMARY:
                # Any input returns to multi-GSTIN menu
                session["state"] = MULTI_GSTIN_MENU
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, _t(session, "MULTI_GSTIN_MENU"))
                return Response(status_code=200)

            # ===================================================
            # PHASE 9: Refund Tracking
            # ===================================================
            if state == REFUND_MENU:
                if text == "1":
                    # New refund claim
                    session["state"] = REFUND_TYPE
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, "Select refund type:\n\n1) Excess Balance\n2) Export Refund\n3) Inverted Duty\n\nBACK = Go Back")
                    return Response(status_code=200)
                elif text == "2":
                    # Check refund status
                    gstin = session.get("data", {}).get("gstin", "")
                    from app.domain.services.refund_service import list_refund_claims
                    try:
                        from app.core.db import get_db as _get_db
                        async for _db in _get_db():
                            claims = await list_refund_claims(gstin, _db)
                            if claims:
                                lines = ["📋 Your Refund Claims:\n"]
                                for c in claims:
                                    lines.append(f"• {c['claim_type']} — ₹{c['amount']:,.2f} — {c['status']}")
                                lines.append("\nMENU = Main Menu\nBACK = Go Back")
                                await _send(wa_id, "\n".join(lines))
                            else:
                                await _send(wa_id, "No refund claims found.\n\nMENU = Main Menu\nBACK = Go Back")
                            break
                    except Exception:
                        await _send(wa_id, "Error fetching refund claims.\n\nMENU = Main Menu\nBACK = Go Back")
                    return Response(status_code=200)
                else:
                    await _send(wa_id, _t(session, "REFUND_MENU"))
                    return Response(status_code=200)

            if state == REFUND_TYPE:
                type_map = {"1": "excess_balance", "2": "export", "3": "inverted_duty"}
                if text in type_map:
                    session.setdefault("data", {})["refund_type"] = type_map[text]
                    session["state"] = REFUND_DETAILS
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, "Enter the refund amount (in ₹):")
                else:
                    await _send(wa_id, "Invalid choice. Select 1, 2, or 3:")
                return Response(status_code=200)

            if state == REFUND_DETAILS:
                try:
                    amount = float(text.replace(",", "").replace("₹", "").strip())
                except ValueError:
                    await _send(wa_id, "Please enter a valid amount (e.g. 50000):")
                    return Response(status_code=200)
                gstin = session.get("data", {}).get("gstin", "")
                claim_type = session.get("data", {}).get("refund_type", "excess_balance")
                period = get_current_gst_period()
                from app.domain.services.refund_service import create_refund_claim
                try:
                    from app.core.db import get_db as _get_db
                    async for _db in _get_db():
                        result = await create_refund_claim(gstin, 0, claim_type, amount, period, _db)
                        await _send(wa_id, f"✅ Refund claim created!\n\nType: {claim_type}\nAmount: ₹{amount:,.2f}\nPeriod: {period}\nStatus: {result['status']}\n\nMENU = Main Menu\nBACK = Go Back")
                        break
                except Exception:
                    logger.exception("Refund claim creation error")
                    await _send(wa_id, "Error creating refund claim.\n\nMENU = Main Menu\nBACK = Go Back")
                session["state"] = pop_state(session)
                session.get("data", {}).pop("refund_type", None)
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            # ===================================================
            # PHASE 9: Notice Management
            # ===================================================
            if state == NOTICE_MENU:
                if text == "1":
                    # View pending notices
                    gstin = session.get("data", {}).get("gstin", "")
                    from app.domain.services.notice_service import list_pending_notices
                    try:
                        from app.core.db import get_db as _get_db
                        async for _db in _get_db():
                            notices = await list_pending_notices(gstin, _db)
                            if notices:
                                lines = ["📋 Pending Notices:\n"]
                                for n in notices:
                                    due = n.get("due_date", "N/A")
                                    lines.append(f"• {n['notice_type']}: {n['description'][:50]}... (Due: {due})")
                                lines.append("\nMENU = Main Menu\nBACK = Go Back")
                                await _send(wa_id, "\n".join(lines))
                            else:
                                await _send(wa_id, "✅ No pending notices!\n\nMENU = Main Menu\nBACK = Go Back")
                            break
                    except Exception:
                        await _send(wa_id, "Error fetching notices.\n\nMENU = Main Menu\nBACK = Go Back")
                    return Response(status_code=200)
                elif text == "2":
                    # Upload notice
                    session["state"] = NOTICE_UPLOAD
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, "Upload the notice document (photo/PDF):")
                    return Response(status_code=200)
                else:
                    await _send(wa_id, _t(session, "NOTICE_MENU"))
                    return Response(status_code=200)

            if state == NOTICE_UPLOAD:
                # Handled by document pipeline — for text, just acknowledge
                await _send(wa_id, "Upload a photo or PDF of the GST notice, or type 'done' to go back.")
                if text.lower() == "done":
                    session["state"] = NOTICE_MENU
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "NOTICE_MENU"))
                return Response(status_code=200)

            # ===================================================
            # PHASE 9: Export Services
            # ===================================================
            if state == EXPORT_MENU:
                # Placeholder for export services sub-menu
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, "Export services feature coming soon!\n\nMENU = Main Menu\nBACK = Go Back")
                return Response(status_code=200)

            # ===================================================
            # PHASE 10: Notification Settings
            # ===================================================
            if state == NOTIFICATION_SETTINGS:
                pref_map = {
                    "1": {"filing_reminders": True, "risk_alerts": False, "status_updates": False},
                    "2": {"filing_reminders": False, "risk_alerts": True, "status_updates": False},
                    "3": {"filing_reminders": False, "risk_alerts": False, "status_updates": True},
                    "4": {"filing_reminders": True, "risk_alerts": True, "status_updates": True},
                    "5": {"filing_reminders": False, "risk_alerts": False, "status_updates": False},
                }
                if text in pref_map:
                    session.setdefault("data", {})["notification_prefs"] = pref_map[text]
                    await session_cache.save_session(wa_id, session)
                    if text == "5":
                        await _send(wa_id, "🔕 Notifications turned off.\n\nMENU = Main Menu\nBACK = Go Back")
                    else:
                        await _send(wa_id, "🔔 Notification preferences updated!\n\nMENU = Main Menu\nBACK = Go Back")
                    session["state"] = SETTINGS_MENU
                    await session_cache.save_session(wa_id, session)
                else:
                    await _send(wa_id, _t(session, "NOTIFICATION_SETTINGS"))
                return Response(status_code=200)

            # --- GST FILING MENU ---
            # Handled by wa_handlers/gst_compliance.py

            # --- MONTHLY COMPLIANCE: PERIOD MENU ---
            # Handled by wa_handlers/gst_compliance.py

            # --- MONTHLY COMPLIANCE: PURCHASE INVOICE UPLOAD ---
            # Handled by wa_handlers/gst_compliance.py

            # --- NIL FILING MENU ---
            # Handled by wa_handlers/gst_compliance.py

            # --- NIL FILING CONFIRM ---
            # Handled by wa_handlers/gst_compliance.py

            # --- PHASE 2: PAYMENT ENTRY ---
            # Handled by wa_handlers/gst_compliance.py

            # --- PHASE 2: COMPOSITION MENU ---
            # Handled by wa_handlers/gst_compliance.py

            # --- PHASE 2: COMPOSITION TURNOVER ENTRY ---
            # Handled by wa_handlers/gst_compliance.py

            # --- PHASE 2: QRMP MENU ---
            # Handled by wa_handlers/gst_compliance.py

            # --- PHASE 2: ANNUAL RETURN MENU ---
            # Handled by wa_handlers/gst_compliance.py

            # --- GST FILING CONFIRM ---
            # Handled by wa_handlers/gst_compliance.py

            # --- ITR FILING DOWNLOAD ---
            # State: ITR_FILING_DOWNLOAD
            # Extracted to: app/api/routes/wa_handlers/itr_doc_upload.py

            # --- BATCH UPLOAD (text commands) ---
            if state == BATCH_UPLOAD:
                if text.lower() == "done":
                    batch = session.get("data", {}).get("batch_invoices", [])
                    count = len(batch)
                    # Move batch to uploaded_invoices
                    session.setdefault("data", {}).setdefault("uploaded_invoices", [])
                    session["data"]["uploaded_invoices"].extend(batch)
                    session["data"]["batch_invoices"] = []
                    session["state"] = MAIN_MENU
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "BATCH_COMPLETE", count=count))
                    # Send summary PDF for all batch invoices
                    if batch:
                        await _send_batch_summary_pdf(wa_id, batch, session)
                    return Response(status_code=200)
                await _send(wa_id, _t(session, "BATCH_UPLOAD_PROMPT"))
                return Response(status_code=200)

            # --- INSIGHTS MENU ---
            if state == INSIGHTS_MENU:
                if text == "1":
                    await _send(wa_id, _t(session, "INSIGHTS_GENERATING"))
                    invoices = session.get("data", {}).get("uploaded_invoices", [])
                    if not invoices:
                        await _send(wa_id, _t(session, "INSIGHTS_NO_DATA"))
                        return Response(status_code=200)
                    summary = aggregate_invoices(invoices)
                    anomalies = await detect_anomalies(invoices)
                    deadlines = get_filing_deadlines()
                    insights = await generate_ai_insights(summary, anomalies, deadlines, lang)
                    await _send(wa_id, insights + "\n\nMENU = Main Menu\nBACK = Go Back")
                    return Response(status_code=200)
                if text == "2":
                    invoices = session.get("data", {}).get("uploaded_invoices", [])
                    if not invoices:
                        await _send(wa_id, _t(session, "INSIGHTS_NO_DATA"))
                        return Response(status_code=200)
                    anomalies = await detect_anomalies(invoices)
                    title = _t(session, "ANOMALY_TITLE")
                    if anomalies.total_anomalies == 0:
                        await _send(wa_id, _t(session, "ANOMALY_CLEAN"))
                        return Response(status_code=200)
                    lines = [title, ""]
                    if anomalies.duplicate_invoice_numbers:
                        lines.append(f"Duplicate invoices: {len(anomalies.duplicate_invoice_numbers)}")
                    if anomalies.invalid_gstins:
                        lines.append(f"Invalid GSTINs: {len(anomalies.invalid_gstins)}")
                    if anomalies.high_value_invoices:
                        lines.append(f"High-value outliers: {len(anomalies.high_value_invoices)}")
                    if anomalies.tax_rate_outliers:
                        lines.append(f"Unusual tax rates: {len(anomalies.tax_rate_outliers)}")
                    if anomalies.missing_fields:
                        lines.append(f"Missing fields: {len(anomalies.missing_fields)}")
                    lines.append(f"\nTotal anomalies: {anomalies.total_anomalies}")
                    lines.append("\nMENU = Main Menu\nBACK = Go Back")
                    await _send(wa_id, "\n".join(lines))
                    return Response(status_code=200)
                await _send(wa_id, _t(session, "INSIGHTS_MENU"))
                return Response(status_code=200)

            # --- SETTINGS MENU ---
            # DEPRECATED: SETTINGS_MENU is now handled by wa_handlers/settings_handler.py
            # (intercepted by the handler chain above before reaching this point)

            # --- SMART UPLOAD (text commands) ---
            if state == SMART_UPLOAD:
                if text.lower() == "done":
                    batch = session.get("data", {}).get("smart_invoices", [])
                    count = len(batch)
                    # Merge smart invoices into uploaded_invoices (dedup by invoice_number)
                    session.setdefault("data", {}).setdefault("uploaded_invoices", [])
                    for inv in batch:
                        _upsert_invoice(session["data"]["uploaded_invoices"], inv)
                    session["data"]["smart_invoices"] = []

                    if count == 0:
                        session["state"] = pop_state(session)
                        await session_cache.save_session(wa_id, session)
                        await _send(wa_id, _t(session, _state_to_screen_key(session["state"])))
                        return Response(status_code=200)

                    # ── Auto-resubmit if user has a changes_requested filing ──
                    try:
                        from app.domain.services.gst_workflow import resubmit_gst_filing
                        resubmitted = await resubmit_gst_filing(wa_id, session, db)
                    except Exception:
                        logger.exception("Auto-resubmit failed for %s", wa_id)
                        resubmitted = None

                    if resubmitted:
                        # Filing was resubmitted to the same CA
                        session["state"] = MAIN_MENU
                        session["stack"] = []
                        await session_cache.save_session(wa_id, session)
                        return Response(status_code=200)

                    # ── Auto-detect GST form type and show filing consent ──
                    invoices = session.get("data", {}).get("uploaded_invoices", [])
                    gstin = session.get("data", {}).get("gstin", "")
                    period = get_current_gst_period()
                    form_type = _detect_gst_form(invoices, gstin)

                    await _send(wa_id, _t(session, "GST_COMPUTING"))

                    if form_type == "GSTR-1":
                        summary = aggregate_invoices(invoices)
                        preview = "\n".join([
                            "--- GSTR-1 Preview ---", "",
                            f"Total Invoices: {summary.total_invoices}",
                            f"B2B Invoices: {summary.b2b_count}",
                            f"B2C Invoices: {summary.b2c_count}",
                            f"Total Taxable: Rs {summary.total_taxable_value:,.0f}",
                            f"Total Tax: Rs {summary.total_tax:,.0f}",
                            f"Total Value: Rs {summary.total_amount:,.0f}",
                        ])
                    else:
                        # Default to GSTR-3B
                        form_type = "GSTR-3B"
                        summary = prepare_gstr3b(invoices)
                        preview = _format_gstr3b(summary)

                    session["data"]["gst_filing_form"] = form_type
                    push_state(session, SMART_UPLOAD)
                    session["state"] = GST_FILING_CONFIRM
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, preview + "\n\n" + _t(
                        session, "GST_FILING_CONFIRM",
                        form_type=form_type, period=period, gstin=gstin,
                    ))
                    return Response(status_code=200)
                await _send(wa_id, _t(session, "UPLOAD_SMART_PROMPT"))
                return Response(status_code=200)

            # --- LANGUAGE MENU ---
            if state == LANG_MENU:
                if text in LANG_NUMBER_MAP:
                    session["lang"] = LANG_NUMBER_MAP[text]
                    session["state"] = pop_state(session)
                    await session_cache.save_session(wa_id, session)
                    await _send(wa_id, _t(session, "LANG_SET", lang_name=LANG_NAMES[_get_lang(session)]))
                    await _send(wa_id, _t(session, _state_to_screen_key(session["state"])))
                    return Response(status_code=200)
                await _send(wa_id, _t(session, "LANG_MENU"))
                return Response(status_code=200)

            # --- WAIT GSTIN ---
            if state == WAIT_GSTIN:
                gstin = text.upper()
                if not is_valid_gstin(gstin):
                    await _send(wa_id, _t(session, "INVALID_GSTIN"))
                    return Response(status_code=200)
                session.setdefault("data", {})["gstin"] = gstin
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, _t(session, "GST_SAVED", gstin=gstin))
                await _send(wa_id, _t(session, "WELCOME_MENU"))
                return Response(status_code=200)

            # fallback
            await _send(wa_id, _t(session, "UNKNOWN_INPUT"))
            return Response(status_code=200)

        # =====================================================
        # ITR DOCUMENT UPLOAD (Form 16 / 26AS / AIS)
        # Strategy: Vision (primary) → Tesseract+LLM (fallback)
        # =====================================================
        if msg["type"] in ("image", "document") and state == ITR_DOC_UPLOAD:
            media = msg[msg["type"]]
            media_id = media.get("id")
            mime = media.get("mime_type") or ("image/jpeg" if msg["type"] == "image" else "")

            if not media_id:
                await _send(wa_id, _t(session, "ITR_DOC_PARSE_FAILED"))
                return Response(status_code=200)

            pending_type = session.get("data", {}).get("itr_docs", {}).get("pending_type", "form16")
            label = _DOC_TYPE_LABELS.get(pending_type, pending_type)
            await _send(wa_id, _t(session, "ITR_DOC_PROCESSING", doc_type=label))

            media_url = await get_media_url(media_id)
            file_bytes = await download_media(media_url)

            # Select the right parser based on document type
            _VISION_PARSERS = {
                "form16": parse_form16_vision,
                "26as": parse_form26as_vision,
                "ais": parse_ais_vision,
            }
            _TEXT_PARSERS = {
                "form16": parse_form16_text,
                "26as": parse_form26as_text,
                "ais": parse_ais_text,
            }

            parsed_dict: dict = {}
            is_image = mime in ("image/jpeg", "image/jpg", "image/png", "image/webp", None)

            # Strategy 1: GPT-4o Vision
            if is_image and file_bytes:
                vision_fn = _VISION_PARSERS.get(pending_type)
                if vision_fn:
                    parsed_dict = await vision_fn(file_bytes, mime or "image/jpeg")
                    if parsed_dict:
                        logger.info("%s parsed via GPT-4o Vision", label)

            # Strategy 2: OCR + LLM fallback
            if not parsed_dict:
                ocr_text = await ocr_extract(file_bytes, mime)
                if ocr_text.strip():
                    text_fn = _TEXT_PARSERS.get(pending_type)
                    if text_fn:
                        parsed_dict = await text_fn(ocr_text)

            if not parsed_dict:
                await _send(wa_id, _t(session, "ITR_DOC_PARSE_FAILED"))
                return Response(status_code=200)

            # Convert to typed dataclass and merge
            merged = dict_to_merged(
                session.get("data", {}).get("itr_docs", {}).get("merged", {})
            )
            if pending_type == "form16":
                f16 = dict_to_parsed_form16(parsed_dict)
                merged = merge_form16(merged, f16)
            elif pending_type == "26as":
                f26 = dict_to_parsed_form26as(parsed_dict)
                merged = merge_form26as(merged, f26)
            elif pending_type == "ais":
                ais_data = dict_to_parsed_ais(parsed_dict)
                merged = merge_ais(merged, ais_data)

            # Save merged data back to session
            session["data"]["itr_docs"]["merged"] = merged_to_dict(merged)
            session["data"]["itr_docs"].setdefault("uploaded", []).append(pending_type)
            session["state"] = ITR_DOC_REVIEW
            await session_cache.save_session(wa_id, session)

            # Send review summary
            summary = format_review_summary(merged, lang)
            await _send(wa_id, summary + _t(session, "ITR_DOC_REVIEW_OPTIONS"))
            return Response(status_code=200)

        # =====================================================
        # INVOICE UPLOAD (image/document) — single or batch
        # Strategy: Vision (primary) → Tesseract+regex+LLM (fallback)
        # Auto-accepts invoices from ANY state for seamless re-upload
        # (e.g. after CA requests changes, user can upload directly)
        # =====================================================
        if msg["type"] in ("image", "document") and state not in (ITR_DOC_UPLOAD,):
            # ---- e-Invoice / e-WayBill upload routing ----
            # When user is in EINVOICE_UPLOAD or EWAYBILL_UPLOAD, route parsed
            # invoice into the correct session list instead of smart_invoices.
            if state in (EINVOICE_UPLOAD, EWAYBILL_UPLOAD):
                _einv_upload_state = state  # remember which flow we're in
            else:
                _einv_upload_state = None

            # Auto-switch to smart upload if not already in an upload state
            # This allows users to upload invoices from ANY state (e.g. after
            # CA requests changes, they can re-upload directly without menu nav)
            if state not in (WAIT_INVOICE_UPLOAD, BATCH_UPLOAD, SMART_UPLOAD, EINVOICE_UPLOAD, EWAYBILL_UPLOAD):
                prev_state = state
                push_state(session, prev_state)
                session["state"] = SMART_UPLOAD
                session.setdefault("data", {})["smart_invoices"] = []
                state = SMART_UPLOAD
                logger.info("Auto-switched %s to SMART_UPLOAD from %s", wa_id, prev_state)
            media = msg[msg["type"]]
            media_id = media.get("id")
            mime = media.get("mime_type") or ("image/jpeg" if msg["type"] == "image" else "")

            if not media_id:
                await _send(wa_id, _t(session, "INVOICE_PARSE_FAIL"))
                return Response(status_code=200)

            await _send(wa_id, _t(session, "INVOICE_PROCESSING"))

            media_url = await get_media_url(media_id)
            file_bytes = await download_media(media_url)

            inv_dict: dict = {}
            parse_method = "none"

            # ---- Strategy 1: GPT-4o Vision (images only) ----
            is_image = mime in (
                "image/jpeg", "image/jpg", "image/png", "image/webp", None,
            )
            if is_image and file_bytes:
                vision_result = await parse_invoice_vision(file_bytes, mime or "image/jpeg")
                if vision_result and vision_result.get("total_amount") is not None:
                    inv_dict = vision_result
                    parse_method = "vision"
                    logger.info("Invoice parsed via GPT-4o Vision")

            # ---- Strategy 2: For PDFs, or when Vision fails ----
            if not inv_dict:
                ocr_text = await ocr_extract(file_bytes, mime)
                parsed = parse_invoice_text(ocr_text)

                # LLM text fallback: always try for better accuracy
                if ocr_text.strip():
                    llm_result = await parse_invoice_llm(ocr_text)
                    if llm_result:
                        # Merge: LLM fills gaps that regex missed
                        merge_fields = [
                            "supplier_name", "supplier_gstin", "receiver_name",
                            "receiver_gstin", "invoice_number", "invoice_date",
                            "hsn_code", "item_description",
                            "taxable_value", "tax_rate", "tax_amount",
                            "total_amount", "cgst_amount", "sgst_amount",
                            "igst_amount", "place_of_supply",
                        ]
                        for fn in merge_fields:
                            if getattr(parsed, fn, None) is None and llm_result.get(fn) is not None:
                                setattr(parsed, fn, llm_result[fn])
                        parse_method = "ocr+llm"
                    else:
                        parse_method = "ocr+regex"

                inv_dict = parsed.__dict__

            # ---- Validate GSTINs ----
            from app.domain.services.gstin_pan_validation import is_valid_gstin
            s_gstin = inv_dict.get("supplier_gstin")
            r_gstin = inv_dict.get("receiver_gstin")
            inv_dict["supplier_gstin_valid"] = is_valid_gstin(s_gstin) if s_gstin else None
            inv_dict["receiver_gstin_valid"] = is_valid_gstin(r_gstin) if r_gstin else None
            inv_dict.setdefault("parse_method", parse_method)

            if _einv_upload_state == EINVOICE_UPLOAD:
                # e-Invoice flow: store in einvoice_invoices, stay in EINVOICE_UPLOAD
                list_key = "einvoice_invoices"
                session.setdefault("data", {}).setdefault(list_key, [])
                was_update = _upsert_invoice(session["data"][list_key], inv_dict)
                count = len(session["data"][list_key])
                session.setdefault("data", {})["last_invoice"] = inv_dict
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, invoice_to_text(session, inv_dict))
                if was_update:
                    await _send(wa_id, f"🧾 Invoice updated ({count} total). Upload more or type 'done'.")
                else:
                    await _send(wa_id, f"🧾 Invoice added ({count} total). Upload more or type 'done'.")
            elif _einv_upload_state == EWAYBILL_UPLOAD:
                # e-WayBill flow: store in ewaybill_invoices, stay in EWAYBILL_UPLOAD
                list_key = "ewaybill_invoices"
                session.setdefault("data", {}).setdefault(list_key, [])
                was_update = _upsert_invoice(session["data"][list_key], inv_dict)
                count = len(session["data"][list_key])
                session.setdefault("data", {})["last_invoice"] = inv_dict
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, invoice_to_text(session, inv_dict))
                if was_update:
                    await _send(wa_id, f"🚛 Invoice updated ({count} total). Upload more or type 'done'.")
                else:
                    await _send(wa_id, f"🚛 Invoice added ({count} total). Upload more or type 'done'.")
            elif state in (BATCH_UPLOAD, SMART_UPLOAD):
                # Smart/batch mode: upsert into list, stay in upload state
                list_key = "smart_invoices" if state == SMART_UPLOAD else "batch_invoices"
                session.setdefault("data", {}).setdefault(list_key, [])
                was_update = _upsert_invoice(session["data"][list_key], inv_dict)
                count = len(session["data"][list_key])
                session.setdefault("data", {})["last_invoice"] = inv_dict
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, invoice_to_text(session, inv_dict))
                # No PDF after each upload — user sees text summary only
                if was_update:
                    await _send(wa_id, _t(session, "INVOICE_UPDATED", count=count))
                else:
                    await _send(wa_id, _t(session, "BATCH_INVOICE_ADDED", count=count))
            else:
                # Single upload mode (legacy WAIT_INVOICE_UPLOAD)
                session.setdefault("data", {})["last_invoice"] = inv_dict
                session.setdefault("data", {}).setdefault("uploaded_invoices", [])
                _upsert_invoice(session["data"]["uploaded_invoices"], inv_dict)
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
                await _send(wa_id, invoice_to_text(session, inv_dict))
                await _send_invoice_pdf(wa_id, inv_dict, session)
                await _send(wa_id, _t(session, "WELCOME_MENU"))

            return Response(status_code=200)

        # fallback for unhandled message types
        await _send(wa_id, _t(session, "UNKNOWN_INPUT"))
        return Response(status_code=200)

    except Exception:
        logger.exception("Webhook error")
        return Response(status_code=200)
