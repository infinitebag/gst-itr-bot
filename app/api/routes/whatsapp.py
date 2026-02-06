import os
import logging
from typing import Dict, Any

from fastapi import APIRouter, Request, Response
import httpx

from app.infrastructure.cache.session_cache import SessionCache
from app.infrastructure.external.whatsapp_media import get_media_url, download_media
from app.domain.services.invoice_parser import parse_invoice_text

logger = logging.getLogger("whatsapp")

router = APIRouter(prefix="", tags=["whatsapp"])

# =========================
# ENV (NO pydantic)
# =========================
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
REDIS_URL = os.getenv("REDIS_URL", "")

GRAPH_URL = "https://graph.facebook.com/v20.0"

session_cache = SessionCache(REDIS_URL)

# =========================
# STATES
# =========================
MAIN_MENU = "MAIN_MENU"
GST_MENU = "GST_MENU"
ITR_MENU = "ITR_MENU"
LANG_MENU = "LANG_MENU"
WAIT_GSTIN = "WAIT_GSTIN"
WAIT_INVOICE_UPLOAD = "WAIT_INVOICE_UPLOAD"


# =========================
# I18N (English + Hindi + Telugu)
# =========================
I18N = {
    "en": {
        "welcome_menu": (
            "👋 Welcome to GST + ITR Bot\n\n"
            "Choose an option:\n"
            "1) GST Services\n"
            "2) ITR Services\n"
            "3) Upload Invoice (OCR)\n"
            "4) Change Language\n\n"
            "Reply with 1/2/3/4\n"
            "At any time:\n"
            "0 = Main Menu\n"
            "9 = Back"
        ),
        "gst_services": "GST Services\n1) Enter GSTIN\n0 = Main Menu\n9 = Back",
        "itr_services": "ITR Services (Phase-3 hooks coming)\n0 = Main Menu\n9 = Back",
        "ask_gstin": "Send GSTIN (15 chars)\n0 = Main Menu\n9 = Back",
        "invalid_gstin": "❌ Invalid GSTIN. Please try again.\n0 = Main Menu\n9 = Back",
        "gst_saved": "✅ GSTIN saved: {gstin}\n\n0 = Main Menu\n9 = Back",
        "upload_invoice_prompt": "📄 Upload invoice (PDF/Image)\n0 = Main Menu\n9 = Back",
        "unknown_input": "❓ Unknown input. Reply 0 for Main Menu.",
        "lang_menu": (
            "🌐 Choose Language:\n"
            "1) English\n"
            "2) हिंदी\n"
            "3) తెలుగు\n\n"
            "Reply 1/2/3\n"
            "0 = Main Menu\n"
            "9 = Back"
        ),
        "lang_set": "✅ Language set to {lang_name}\n\n0 = Main Menu\n9 = Back",
        "invoice_parsed_title": "✅ Invoice Parsed",
        "invoice_fields": (
            "Supplier GSTIN: {supplier_gstin}\n"
            "Receiver GSTIN: {receiver_gstin}\n"
            "Invoice No: {invoice_number}\n"
            "Invoice Date: {invoice_date}\n"
            "Taxable Value: {taxable_value}\n"
            "Tax Amount: {tax_amount}\n"
            "Total Amount: {total_amount}\n\n"
            "0 = Main Menu\n9 = Back"
        ),
        "invoice_parse_fail": "❌ Could not parse invoice.\n0 = Main Menu\n9 = Back",
    },
    "hi": {
        "welcome_menu": (
            "👋 GST + ITR बॉट में आपका स्वागत है\n\n"
            "एक विकल्प चुनें:\n"
            "1) GST सेवाएँ\n"
            "2) ITR सेवाएँ\n"
            "3) इनवॉइस अपलोड (OCR)\n"
            "4) भाषा बदलें\n\n"
            "1/2/3/4 में उत्तर दें\n"
            "किसी भी समय:\n"
            "0 = मुख्य मेनू\n"
            "9 = पीछे"
        ),
        "gst_services": "GST सेवाएँ\n1) GSTIN दर्ज करें\n0 = मुख्य मेनू\n9 = पीछे",
        "itr_services": "ITR सेवाएँ (Phase-3 hooks जल्द)\n0 = मुख्य मेनू\n9 = पीछे",
        "ask_gstin": "GSTIN भेजें (15 अक्षर)\n0 = मुख्य मेनू\n9 = पीछे",
        "invalid_gstin": "❌ गलत GSTIN. फिर से कोशिश करें.\n0 = मुख्य मेनू\n9 = पीछे",
        "gst_saved": "✅ GSTIN सेव हो गया: {gstin}\n\n0 = मुख्य मेनू\n9 = पीछे",
        "upload_invoice_prompt": "📄 इनवॉइस अपलोड करें (PDF/Image)\n0 = मुख्य मेनू\n9 = पीछे",
        "unknown_input": "❓ समझ नहीं आया. मुख्य मेनू के लिए 0 दबाएँ.",
        "lang_menu": (
            "🌐 भाषा चुनें:\n"
            "1) English\n"
            "2) हिंदी\n"
            "3) తెలుగు\n\n"
            "1/2/3 में उत्तर दें\n"
            "0 = मुख्य मेनू\n"
            "9 = पीछे"
        ),
        "lang_set": "✅ भाषा सेट हो गई: {lang_name}\n\n0 = मुख्य मेनू\n9 = पीछे",
        "invoice_parsed_title": "✅ इनवॉइस पार्स हुआ",
        "invoice_fields": (
            "Supplier GSTIN: {supplier_gstin}\n"
            "Receiver GSTIN: {receiver_gstin}\n"
            "Invoice No: {invoice_number}\n"
            "Invoice Date: {invoice_date}\n"
            "Taxable Value: {taxable_value}\n"
            "Tax Amount: {tax_amount}\n"
            "Total Amount: {total_amount}\n\n"
            "0 = मुख्य मेनू\n9 = पीछे"
        ),
        "invoice_parse_fail": "❌ इनवॉइस पार्स नहीं हुआ.\n0 = मुख्य मेनू\n9 = पीछे",
    },
    "te": {
        "welcome_menu": (
            "👋 GST + ITR బాట్‌కు స్వాగతం\n\n"
            "ఒక ఎంపికను ఎంచుకోండి:\n"
            "1) GST సేవలు\n"
            "2) ITR సేవలు\n"
            "3) ఇన్వాయిస్ అప్‌లోడ్ (OCR)\n"
            "4) భాష మార్చండి\n\n"
            "1/2/3/4 తో రిప్లై చేయండి\n"
            "ఎప్పుడైనా:\n"
            "0 = మెయిన్ మెనూ\n"
            "9 = వెనక్కి"
        ),
        "gst_services": "GST సేవలు\n1) GSTIN ఇవ్వండి\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
        "itr_services": "ITR సేవలు (Phase-3 hooks త్వరలో)\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
        "ask_gstin": "GSTIN పంపండి (15 అక్షరాలు)\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
        "invalid_gstin": "❌ తప్పు GSTIN. మళ్లీ ప్రయత్నించండి.\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
        "gst_saved": "✅ GSTIN సేవ్ అయ్యింది: {gstin}\n\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
        "upload_invoice_prompt": "📄 ఇన్వాయిస్ అప్లోడ్ చేయండి (PDF/Image)\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
        "unknown_input": "❓ అర్థం కాలేదు. మెయిన్ మెనూ కోసం 0 ఇవ్వండి.",
        "lang_menu": (
            "🌐 భాష ఎంచుకోండి:\n"
            "1) English\n"
            "2) हिंदी\n"
            "3) తెలుగు\n\n"
            "1/2/3 తో రిప్లై చేయండి\n"
            "0 = మెయిన్ మెనూ\n"
            "9 = వెనక్కి"
        ),
        "lang_set": "✅ భాష సెట్ అయ్యింది: {lang_name}\n\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
        "invoice_parsed_title": "✅ ఇన్వాయిస్ పార్స్ అయ్యింది",
        "invoice_fields": (
            "Supplier GSTIN: {supplier_gstin}\n"
            "Receiver GSTIN: {receiver_gstin}\n"
            "Invoice No: {invoice_number}\n"
            "Invoice Date: {invoice_date}\n"
            "Taxable Value: {taxable_value}\n"
            "Tax Amount: {tax_amount}\n"
            "Total Amount: {total_amount}\n\n"
            "0 = మెయిన్ మెనూ\n9 = వెనక్కి"
        ),
        "invoice_parse_fail": "❌ ఇన్వాయిస్ పార్స్ కాలేదు.\n0 = మెయిన్ మెనూ\n9 = వెనక్కి",
    },
}

LANG_NAMES = {"en": "English", "hi": "हिंदी", "te": "తెలుగు"}


def get_lang(session: Dict[str, Any]) -> str:
    lang = session.get("lang") or "en"
    return lang if lang in I18N else "en"


def t(session: Dict[str, Any], key: str, **kwargs) -> str:
    lang = get_lang(session)
    msg = I18N[lang].get(key) or I18N["en"].get(key) or key
    if kwargs:
        return msg.format(**kwargs)
    return msg


# =========================
# WhatsApp send
# =========================
async def whatsapp_send_text(wa_id: str, text: str) -> None:
    url = f"{GRAPH_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json=payload, headers=headers)
        logger.info("WhatsApp send status=%s body=%s", r.status_code, r.text)


# =========================
# Nav stack helpers
# =========================
def push_state(session: Dict[str, Any], state: str) -> None:
    session.setdefault("stack", []).append(state)


def pop_state(session: Dict[str, Any]) -> str:
    stack = session.get("stack", [])
    return stack.pop() if stack else MAIN_MENU


async def show_main_menu(wa_id: str, session: Dict[str, Any]) -> None:
    session["state"] = MAIN_MENU
    session["stack"] = []
    await session_cache.save_session(wa_id, session)
    await whatsapp_send_text(wa_id, t(session, "welcome_menu"))


# =========================
# GSTIN validation (simple)
# =========================
def is_valid_gstin(gstin: str) -> bool:
    return len(gstin) == 15 and gstin[:2].isdigit()


# =========================
# OCR HOOK (Phase-3)
# =========================
async def extract_text_from_invoice_bytes(data: bytes, mime: str) -> str:
    # 🔌 Replace with real OCR engine later
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def invoice_to_text(session: Dict[str, Any], d: Dict[str, Any]) -> str:
    return (
        f"{t(session, 'invoice_parsed_title')}\n\n"
        + t(
            session,
            "invoice_fields",
            supplier_gstin=d.get("supplier_gstin"),
            receiver_gstin=d.get("receiver_gstin"),
            invoice_number=d.get("invoice_number"),
            invoice_date=d.get("invoice_date"),
            taxable_value=d.get("taxable_value"),
            tax_amount=d.get("tax_amount"),
            total_amount=d.get("total_amount"),
        )
    )


# ==========================================================
# WEBHOOK VERIFY (GET)
# ==========================================================
@router.get("/webhook")
async def verify(request: Request):
    q = request.query_params
    if (
        q.get("hub.mode") == "subscribe"
        and q.get("hub.verify_token") == WHATSAPP_VERIFY_TOKEN
    ):
        return Response(content=q.get("hub.challenge"))
    return Response(status_code=403)


# ==========================================================
# WEBHOOK INBOUND (POST)
# ==========================================================
@router.post("/webhook")
async def inbound(request: Request):
    payload = await request.json()
    logger.info("Inbound WhatsApp payload: %s", payload)

    try:
        value = payload["entry"][0]["changes"][0]["value"]

        # Status callbacks should not break parsing
        if "statuses" in value:
            return Response(status_code=200)

        msg = value["messages"][0]
        wa_id = msg["from"]

        session = await session_cache.get_session(wa_id)
        state = session.get("state", MAIN_MENU)

        # ===== universal nav =====
        if msg["type"] == "text":
            text = msg["text"]["body"].strip()

            if text == "0":
                await show_main_menu(wa_id, session)
                return Response(status_code=200)

            if text == "9":
                session["state"] = pop_state(session)
                await session_cache.save_session(wa_id, session)
                # show screen based on popped state
                if session["state"] == MAIN_MENU:
                    await whatsapp_send_text(wa_id, t(session, "welcome_menu"))
                elif session["state"] == LANG_MENU:
                    await whatsapp_send_text(wa_id, t(session, "lang_menu"))
                elif session["state"] == GST_MENU:
                    await whatsapp_send_text(wa_id, t(session, "gst_services"))
                else:
                    await whatsapp_send_text(wa_id, t(session, "welcome_menu"))
                return Response(status_code=200)

        # =====================
        # MAIN MENU
        # =====================
        if state == MAIN_MENU and msg["type"] == "text":
            if text == "1":
                push_state(session, MAIN_MENU)
                session["state"] = GST_MENU
                await session_cache.save_session(wa_id, session)
                await whatsapp_send_text(wa_id, t(session, "gst_services"))
                return Response(status_code=200)

            if text == "2":
                await whatsapp_send_text(wa_id, t(session, "itr_services"))
                return Response(status_code=200)

            if text == "3":
                push_state(session, MAIN_MENU)
                session["state"] = WAIT_INVOICE_UPLOAD
                await session_cache.save_session(wa_id, session)
                await whatsapp_send_text(wa_id, t(session, "upload_invoice_prompt"))
                return Response(status_code=200)

            if text == "4":
                push_state(session, MAIN_MENU)
                session["state"] = LANG_MENU
                await session_cache.save_session(wa_id, session)
                await whatsapp_send_text(wa_id, t(session, "lang_menu"))
                return Response(status_code=200)

        # =====================
        # LANGUAGE MENU
        # =====================
        if state == LANG_MENU and msg["type"] == "text":
            if text == "1":
                session["lang"] = "en"
            elif text == "2":
                session["lang"] = "hi"
            elif text == "3":
                session["lang"] = "te"
            else:
                await whatsapp_send_text(wa_id, t(session, "lang_menu"))
                return Response(status_code=200)

            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await whatsapp_send_text(
                wa_id, t(session, "lang_set", lang_name=LANG_NAMES[get_lang(session)])
            )
            await whatsapp_send_text(wa_id, t(session, "welcome_menu"))
            return Response(status_code=200)

        # =====================
        # GST MENU
        # =====================
        if state == GST_MENU and msg["type"] == "text":
            if text == "1":
                push_state(session, GST_MENU)
                session["state"] = WAIT_GSTIN
                await session_cache.save_session(wa_id, session)
                await whatsapp_send_text(wa_id, t(session, "ask_gstin"))
                return Response(status_code=200)
            await whatsapp_send_text(wa_id, t(session, "gst_services"))
            return Response(status_code=200)

        if state == WAIT_GSTIN and msg["type"] == "text":
            gstin = text.upper()
            if not is_valid_gstin(gstin):
                await whatsapp_send_text(wa_id, t(session, "invalid_gstin"))
                return Response(status_code=200)

            session.setdefault("data", {})["gstin"] = gstin
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await whatsapp_send_text(wa_id, t(session, "gst_saved", gstin=gstin))
            await whatsapp_send_text(wa_id, t(session, "welcome_menu"))
            return Response(status_code=200)

        # =====================
        # INVOICE UPLOAD (image/document)
        # =====================
        if state == WAIT_INVOICE_UPLOAD and msg["type"] in ("image", "document"):
            media = msg[msg["type"]]
            media_id = media.get("id")
            mime = media.get("mime_type") or ("image/jpeg" if msg["type"] == "image" else "")

            if not media_id:
                await whatsapp_send_text(wa_id, t(session, "invoice_parse_fail"))
                return Response(status_code=200)

            media_url = await get_media_url(media_id)
            file_bytes = await download_media(media_url)

            ocr_text = await extract_text_from_invoice_bytes(file_bytes, mime)
            parsed = parse_invoice_text(ocr_text)

            # save parsed
            session.setdefault("data", {})["last_invoice"] = parsed.__dict__
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)

            await whatsapp_send_text(wa_id, invoice_to_text(session, session["data"]["last_invoice"]))
            await whatsapp_send_text(wa_id, t(session, "welcome_menu"))
            return Response(status_code=200)

        # fallback
        await whatsapp_send_text(wa_id, t(session, "unknown_input"))
        return Response(status_code=200)

    except Exception:
        logger.exception("Webhook error")
        return Response(status_code=200)