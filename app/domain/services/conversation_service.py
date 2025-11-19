from datetime import date
import calendar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.db.models import User, Session
from app.domain.i18n import t
from app.infrastructure.external.whatsapp_client import send_whatsapp_text
from app.infrastructure.db.repositories import InvoiceRepository
from app.domain.services.gst_service import prepare_gstr3b

async def handle_incoming_message(db: AsyncSession, value: dict, message: dict):
    number = message["from"]
    text = (message["text"] or {}).get("body", "").strip()

    user = await _get_or_create_user(db, number)
    session = await _get_or_create_session(db, user)

    if session.step == "LANG_SELECT":
        return await _step_lang_select(db, user, session, text)

    if session.step == "MAIN_MENU":
        return await _step_main_menu(db, user, session, text)

    if session.step == "GST_ASK_PERIOD":
        return await _step_gst_period(db, user, session, text)

async def _get_or_create_user(db, number):
    result = await db.execute(select(User).where(User.whatsapp_number == number))
    user = result.scalar_one_or_none()
    if not user:
        user = User(whatsapp_number=number)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user

async def _get_or_create_session(db, user):
    result = await db.execute(
        select(Session).where(Session.user_id == user.id, Session.active == True)
    )
    session = result.scalar_one_or_none()
    if not session:
        session = Session(user_id=user.id, language="en", step="LANG_SELECT")
        db.add(session)
        await db.commit()
        await send_whatsapp_text(user.whatsapp_number, t("LANG_PROMPT", "en"))
        return session
    return session

async def _step_lang_select(db, user, session, text):
    mapping = {"1":"en","2":"hi","3":"gu","4":"ta","5":"te"}
    if text not in mapping:
        return await send_whatsapp_text(user.whatsapp_number, "Invalid")

    session.language = mapping[text]
    session.step = "MAIN_MENU"
    db.add(session)
    await db.commit()
    await send_whatsapp_text(user.whatsapp_number, t("MAIN_MENU", session.language))

async def _step_main_menu(db, user, session, text):
    lang = session.language
    if text == "1":
        session.step = "GST_ASK_PERIOD"
        db.add(session)
        await db.commit()
        return await send_whatsapp_text(user.whatsapp_number, t("ASK_GST_PERIOD", lang))

    if text == "2":
        return await send_whatsapp_text(user.whatsapp_number, "ITR will be added.")

    if text == "3":
        return await send_whatsapp_text(user.whatsapp_number, "Send invoice image or PDF.")

    if text == "4":
        return await send_whatsapp_text(user.whatsapp_number, "GST + ITR Assistant.")

    return await send_whatsapp_text(user.whatsapp_number, t("MAIN_MENU", lang))

async def _step_gst_period(db, user, session, text):
    try:
        year, month = map(int, text.split("-"))
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
    except:
        return await send_whatsapp_text(user.whatsapp_number, "Invalid period.")

    repo = InvoiceRepository(db)
    summary = await prepare_gstr3b(str(user.id), start, end, repo)

    msg = (
        f"GSTR-3B for {text}:\n"
        f"Invoices: {summary.total_invoices}\n"
        f"Taxable: ₹{summary.total_taxable}\n"
        f"Tax: ₹{summary.total_tax}"
    )
    await send_whatsapp_text(user.whatsapp_number, msg)

    session.step = "MAIN_MENU"
    db.add(session)
    await db.commit()
    await send_whatsapp_text(user.whatsapp_number, t("MAIN_MENU", session.language))