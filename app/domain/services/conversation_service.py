from app.infrastructure.cache.session_cache import (
    get_cached_session,
    cache_session,
)
from app.domain.services.conversation_text import TEXT


async def send_text(send_fn, wa_id: str, text: str):
    await send_fn(wa_id, text)


async def handle_message(
    *,
    wa_id: str,
    text: str,
    session_cache,
    send_fn,
):
    session = await get_cached_session(session_cache, wa_id)
    lang = session.get("lang", "en")
    state = session.get("state", "MAIN_MENU")

    # 🔢 GLOBAL CONTROLS
    if text == "0":
        session["state"] = "MAIN_MENU"
        session["stack"] = []
        await cache_session(session_cache, wa_id, session)
        await send_text(send_fn, wa_id, TEXT[lang]["WELCOME"])
        return

    if text == "9" and session["stack"]:
        session["state"] = session["stack"].pop()
        await cache_session(session_cache, wa_id, session)

    # 🏠 MAIN MENU
    if state == "MAIN_MENU":
        if text == "1":
            session["stack"].append("MAIN_MENU")
            session["state"] = "ASK_GSTIN"
            await cache_session(session_cache, wa_id, session)
            await send_text(send_fn, wa_id, TEXT[lang]["ASK_GSTIN"])
            return

        if text == "3":
            session["stack"].append("MAIN_MENU")
            session["state"] = "WAIT_INVOICE_UPLOAD"
            await cache_session(session_cache, wa_id, session)
            await send_text(send_fn, wa_id, TEXT[lang]["UPLOAD_INVOICE"])
            return

        if text == "4":
            session["lang"] = "hi" if lang == "en" else "en"
            await cache_session(session_cache, wa_id, session)
            await send_text(send_fn, wa_id, TEXT[session["lang"]]["LANG_SET"])
            await send_text(send_fn, wa_id, TEXT[session["lang"]]["WELCOME"])
            return

        await send_text(send_fn, wa_id, TEXT[lang]["INVALID"])
        return