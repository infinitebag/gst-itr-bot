# app/api/routes/wa_handlers/itr_filing_flow.py
"""ITR manual filing flows — ITR-1, ITR-2, ITR-4, and smart form routing.

States handled:
    ITR_MENU, ITR_ROUTE_ASK_CG, ITR_ROUTE_ASK_BIZ, ITR_ROUTE_RESULT,
    ITR_ROUTE_CHOOSE_FORM,
    ITR1_ASK_PAN through ITR1_ASK_TDS (9 states),
    ITR2_ASK_PAN through ITR2_ASK_TDS (11 states),
    ITR4_ASK_PAN through ITR4_ASK_TDS (8 states),
    ITR4_GST_LINK_CONFIRM
"""

from __future__ import annotations
import logging
from typing import Any, Callable, Awaitable
from decimal import Decimal
from fastapi import Response

logger = logging.getLogger("wa_handlers.itr_filing_flow")

# State constants
ITR_MENU = "ITR_MENU"

# Smart form routing states
ITR_ROUTE_ASK_CG = "ITR_ROUTE_ASK_CG"
ITR_ROUTE_ASK_BIZ = "ITR_ROUTE_ASK_BIZ"
ITR_ROUTE_RESULT = "ITR_ROUTE_RESULT"
ITR_ROUTE_CHOOSE_FORM = "ITR_ROUTE_CHOOSE_FORM"

# ITR-1 flow states
ITR1_ASK_PAN = "ITR1_ASK_PAN"
ITR1_ASK_NAME = "ITR1_ASK_NAME"
ITR1_ASK_DOB = "ITR1_ASK_DOB"
ITR1_ASK_GENDER = "ITR1_ASK_GENDER"
ITR1_ASK_SALARY = "ITR1_ASK_SALARY"
ITR1_ASK_OTHER_INCOME = "ITR1_ASK_OTHER_INCOME"
ITR1_ASK_80C = "ITR1_ASK_80C"
ITR1_ASK_80D = "ITR1_ASK_80D"
ITR1_ASK_TDS = "ITR1_ASK_TDS"

# ITR-2 flow states
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

# ITR-4 flow states
ITR4_ASK_PAN = "ITR4_ASK_PAN"
ITR4_ASK_NAME = "ITR4_ASK_NAME"
ITR4_ASK_DOB = "ITR4_ASK_DOB"
ITR4_ASK_GENDER = "ITR4_ASK_GENDER"
ITR4_ASK_TYPE = "ITR4_ASK_TYPE"
ITR4_ASK_TURNOVER = "ITR4_ASK_TURNOVER"
ITR4_ASK_80C = "ITR4_ASK_80C"
ITR4_ASK_TDS = "ITR4_ASK_TDS"

# GST-ITR linking state
ITR4_GST_LINK_CONFIRM = "ITR4_GST_LINK_CONFIRM"

# Other states referenced
ITR_DOC_TYPE_MENU = "ITR_DOC_TYPE_MENU"
ITR_FILING_DOWNLOAD = "ITR_FILING_DOWNLOAD"
MAIN_MENU = "MAIN_MENU"

HANDLED_STATES = {
    ITR_MENU,
    ITR_ROUTE_ASK_CG,
    ITR_ROUTE_ASK_BIZ,
    ITR_ROUTE_RESULT,
    ITR_ROUTE_CHOOSE_FORM,
    ITR1_ASK_PAN,
    ITR1_ASK_NAME,
    ITR1_ASK_DOB,
    ITR1_ASK_GENDER,
    ITR1_ASK_SALARY,
    ITR1_ASK_OTHER_INCOME,
    ITR1_ASK_80C,
    ITR1_ASK_80D,
    ITR1_ASK_TDS,
    ITR2_ASK_PAN,
    ITR2_ASK_NAME,
    ITR2_ASK_DOB,
    ITR2_ASK_GENDER,
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
    ITR4_ASK_GENDER,
    ITR4_ASK_TYPE,
    ITR4_ASK_TURNOVER,
    ITR4_ASK_80C,
    ITR4_ASK_TDS,
    ITR4_GST_LINK_CONFIRM,
}


def _parse_number(text: str) -> float | None:
    """Parse a number from user text, stripping commas and currency symbols."""
    cleaned = text.replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


async def handle(
    state: str,
    text: str,
    wa_id: str,
    session: dict,
    *,
    session_cache: Any,
    send: Callable[..., Awaitable],
    send_buttons: Callable[..., Awaitable],
    send_menu_result: Callable[..., Awaitable],
    t: Callable,
    push_state: Callable,
    pop_state: Callable,
    state_to_screen_key: Callable,
    get_lang: Callable | None = None,
    **_extra: Any,
) -> Response | None:
    """Handle ITR filing flow states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    # Import services here to avoid circular imports
    from app.domain.services.itr_service import (
        ITR1Input,
        ITR2Input,
        ITR4Input,
        compute_itr1_dynamic as compute_itr1,
        compute_itr2_dynamic as compute_itr2,
        compute_itr4_dynamic as compute_itr4,
        format_itr_result,
    )
    from app.domain.services.gst_itr_linker import (
        get_gst_data_from_session,
        gst_link_to_dict,
    )

    lang = get_lang(session) if get_lang else session.get("lang", "en")

    # === ITR_MENU ===
    if state == ITR_MENU:
        if text == "1":
            # Smart form routing — ask eligibility questions
            push_state(session, ITR_MENU)
            session["state"] = ITR_ROUTE_ASK_CG
            session.setdefault("data", {})["itr_route"] = {}
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ROUTE_ASK_CG"))
            return Response(status_code=200)
        if text == "2":
            # Upload Documents (Form 16 / 26AS / AIS)
            push_state(session, ITR_MENU)
            session["state"] = ITR_DOC_TYPE_MENU
            session.setdefault("data", {})["itr_docs"] = {
                "merged": {},
                "uploaded": [],
            }
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_DOC_TYPE_MENU"))
            return Response(status_code=200)
        if text == "3":
            # Refund Status
            await send(wa_id, t(session, "ITR_REFUND_STATUS"))
            return Response(status_code=200)
        if text == "4":
            # Filed Returns — show filing history
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.repositories.itr_draft_repository import ITRDraftRepository
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        repo = ITRDraftRepository(db)
                        drafts = await repo.get_by_user(user.id, limit=5)
                        if drafts:
                            lines = [t(session, "ITR_FILED_RETURNS_HEADER")]
                            for d in drafts:
                                status_display = d.status.replace("_", " ").title()
                                ca_note = f"\nCA Notes: {d.ca_notes}" if d.ca_notes else ""
                                lines.append(
                                    t(session, "ITR_WORKFLOW_STATUS_MSG",
                                       form_type=d.form_type,
                                       ay=d.assessment_year,
                                       status=status_display,
                                       ca_notes=ca_note)
                                )
                            await send(wa_id, "\n---\n".join(lines))
                        else:
                            await send(wa_id, t(session, "ITR_NO_DRAFTS"))
                    else:
                        await send(wa_id, t(session, "ITR_NO_DRAFTS"))
            except Exception:
                logger.exception("ITR filed returns check failed for %s", wa_id)
                await send(wa_id, t(session, "ITR_NO_DRAFTS"))
            return Response(status_code=200)
        await send(wa_id, t(session, "ITR_SERVICES"))
        return Response(status_code=200)

    # === SMART FORM ROUTING ===
    if state == ITR_ROUTE_ASK_CG:
        if text == "1":
            session["data"]["itr_route"]["has_cg"] = True
            session["state"] = ITR_ROUTE_ASK_BIZ
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ROUTE_ASK_BIZ"))
        elif text == "2":
            session["data"]["itr_route"]["has_cg"] = False
            session["state"] = ITR_ROUTE_ASK_BIZ
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ROUTE_ASK_BIZ"))
        else:
            await send(wa_id, t(session, "ITR_ROUTE_ASK_CG"))
        return Response(status_code=200)

    if state == ITR_ROUTE_ASK_BIZ:
        if text == "1":
            session["data"]["itr_route"]["has_biz"] = True
        elif text == "2":
            session["data"]["itr_route"]["has_biz"] = False
        else:
            await send(wa_id, t(session, "ITR_ROUTE_ASK_BIZ"))
            return Response(status_code=200)

        # Determine recommended form
        route = session["data"]["itr_route"]
        has_cg = route.get("has_cg", False)
        has_biz = route.get("has_biz", False)

        if has_cg:
            detected_form = "ITR-2"
        elif has_biz:
            detected_form = "ITR-4"
        else:
            detected_form = "ITR-1"

        session["data"]["itr_route"]["detected_form"] = detected_form
        session["state"] = ITR_ROUTE_RESULT
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ROUTE_DETECTED", form_type=detected_form))
        return Response(status_code=200)

    if state == ITR_ROUTE_RESULT:
        detected_form = session.get("data", {}).get("itr_route", {}).get("detected_form", "ITR-1")
        if text == "1":
            # Proceed with detected form
            if detected_form == "ITR-1":
                session["state"] = ITR1_ASK_PAN
                session.setdefault("data", {})["itr1"] = {}
            elif detected_form == "ITR-2":
                session["state"] = ITR2_ASK_PAN
                session.setdefault("data", {})["itr2"] = {}
            else:
                session["state"] = ITR4_ASK_PAN
                session.setdefault("data", {})["itr4"] = {}
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ASK_PAN"))
        elif text == "2":
            # Choose different form
            session["state"] = ITR_ROUTE_CHOOSE_FORM
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ROUTE_CHOOSE_FORM"))
        else:
            await send(wa_id, t(session, "ITR_ROUTE_DETECTED", form_type=detected_form))
        return Response(status_code=200)

    if state == ITR_ROUTE_CHOOSE_FORM:
        if text == "1":
            session["state"] = ITR1_ASK_PAN
            session.setdefault("data", {})["itr1"] = {}
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ASK_PAN"))
        elif text == "2":
            session["state"] = ITR2_ASK_PAN
            session.setdefault("data", {})["itr2"] = {}
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ASK_PAN"))
        elif text == "3":
            session["state"] = ITR4_ASK_PAN
            session.setdefault("data", {})["itr4"] = {}
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ASK_PAN"))
        else:
            await send(wa_id, t(session, "ITR_ROUTE_CHOOSE_FORM"))
        return Response(status_code=200)

    # === ITR-1 FLOW: Personal Details ===
    if state == ITR1_ASK_PAN:
        pan = text.strip().upper()
        if len(pan) != 10 or not pan[:5].isalpha() or not pan[5:9].isdigit() or not pan[9].isalpha():
            await send(wa_id, t(session, "ITR_INVALID_PAN"))
            return Response(status_code=200)
        session["data"]["itr1"]["pan"] = pan
        session["state"] = ITR1_ASK_NAME
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_NAME"))
        return Response(status_code=200)

    if state == ITR1_ASK_NAME:
        name = text.strip()
        if len(name) < 2:
            await send(wa_id, t(session, "ITR_INVALID_NAME"))
            return Response(status_code=200)
        session["data"]["itr1"]["name"] = name
        session["state"] = ITR1_ASK_DOB
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_DOB"))
        return Response(status_code=200)

    if state == ITR1_ASK_DOB:
        dob = text.strip().replace("-", "/")
        parts = dob.split("/")
        valid_dob = False
        if len(parts) == 3:
            try:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                from datetime import date as _date
                _date(y, m, d)  # validate
                valid_dob = True
            except (ValueError, IndexError):
                pass
        if not valid_dob:
            await send(wa_id, t(session, "ITR_INVALID_DOB"))
            return Response(status_code=200)
        session["data"]["itr1"]["dob"] = dob
        session["state"] = ITR1_ASK_GENDER
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_GENDER"))
        return Response(status_code=200)

    if state == ITR1_ASK_GENDER:
        gender_map = {"1": "M", "2": "F", "3": "O", "m": "M", "f": "F", "o": "O",
                      "male": "M", "female": "F", "other": "O"}
        g = gender_map.get(text.strip().lower())
        if not g:
            await send(wa_id, t(session, "ITR_ASK_GENDER"))
            return Response(status_code=200)
        session["data"]["itr1"]["gender"] = g
        session["state"] = ITR1_ASK_SALARY
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_SALARY"))
        return Response(status_code=200)

    # === ITR-1 FLOW: Income & Deductions ===
    if state == ITR1_ASK_SALARY:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr1"]["salary"] = val
        session["state"] = ITR1_ASK_OTHER_INCOME
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_OTHER_INCOME"))
        return Response(status_code=200)

    if state == ITR1_ASK_OTHER_INCOME:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr1"]["other_income"] = val
        session["state"] = ITR1_ASK_80C
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_80C"))
        return Response(status_code=200)

    if state == ITR1_ASK_80C:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr1"]["sec_80c"] = val
        session["state"] = ITR1_ASK_80D
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_80D"))
        return Response(status_code=200)

    if state == ITR1_ASK_80D:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr1"]["sec_80d"] = val
        session["state"] = ITR1_ASK_TDS
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_TDS"))
        return Response(status_code=200)

    if state == ITR1_ASK_TDS:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr1"]["tds"] = val
        await send(wa_id, t(session, "ITR_COMPUTING"))
        d = session["data"]["itr1"]
        try:
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
            formatted = format_itr_result(result, lang)
            # Store result for PDF/JSON download
            session["data"]["itr_last_result"] = {
                "form_type": "ITR-1",
                "input_data": d,
                "input_type": "manual",
            }
            # Auto-create ITR draft and send to CA
            auto_ca_msg = ""
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.itr_workflow import create_itr_draft_from_session

                form_type = "ITR-1"
                async for db in _get_db():
                    draft = await create_itr_draft_from_session(wa_id, session, form_type, db)
                    if draft.status == "pending_ca_review" and draft.ca_id:
                        auto_ca_msg = "\n\n" + t(session, "ITR_AUTO_SENT_TO_CA", form_type=form_type)
                    elif draft.status == "pending_ca_review" and not draft.ca_id:
                        auto_ca_msg = "\n\n" + t(session, "ITR_QUEUED_FOR_REVIEW", form_type=form_type)
            except Exception:
                logger.exception("Auto ITR draft creation failed for %s", wa_id)
            session["state"] = ITR_FILING_DOWNLOAD
            await session_cache.save_session(wa_id, session)
            await send(
                wa_id,
                formatted + auto_ca_msg + t(session, "ITR_FILING_OPTIONS"),
            )
        except Exception:
            logger.exception("ITR-1 computation failed")
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_RESULT_ERROR"))
        return Response(status_code=200)

    # === ITR-2 FLOW: Personal Details ===
    if state == ITR2_ASK_PAN:
        pan = text.strip().upper()
        if len(pan) != 10 or not pan[:5].isalpha() or not pan[5:9].isdigit() or not pan[9].isalpha():
            await send(wa_id, t(session, "ITR_INVALID_PAN"))
            return Response(status_code=200)
        session["data"]["itr2"]["pan"] = pan
        session["state"] = ITR2_ASK_NAME
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_NAME"))
        return Response(status_code=200)

    if state == ITR2_ASK_NAME:
        name = text.strip()
        if len(name) < 2:
            await send(wa_id, t(session, "ITR_INVALID_NAME"))
            return Response(status_code=200)
        session["data"]["itr2"]["name"] = name
        session["state"] = ITR2_ASK_DOB
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_DOB"))
        return Response(status_code=200)

    if state == ITR2_ASK_DOB:
        dob = text.strip().replace("-", "/")
        parts = dob.split("/")
        valid_dob = False
        if len(parts) == 3:
            try:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                from datetime import date as _date
                _date(y, m, d)  # validate
                valid_dob = True
            except (ValueError, IndexError):
                pass
        if not valid_dob:
            await send(wa_id, t(session, "ITR_INVALID_DOB"))
            return Response(status_code=200)
        session["data"]["itr2"]["dob"] = dob
        session["state"] = ITR2_ASK_GENDER
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_GENDER"))
        return Response(status_code=200)

    if state == ITR2_ASK_GENDER:
        gender_map = {"1": "M", "2": "F", "3": "O", "m": "M", "f": "F", "o": "O",
                      "male": "M", "female": "F", "other": "O"}
        g = gender_map.get(text.strip().lower())
        if not g:
            await send(wa_id, t(session, "ITR_ASK_GENDER"))
            return Response(status_code=200)
        session["data"]["itr2"]["gender"] = g
        session["state"] = ITR2_ASK_SALARY
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_SALARY"))
        return Response(status_code=200)

    # === ITR-2 FLOW: Income & Capital Gains ===
    if state == ITR2_ASK_SALARY:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr2"]["salary"] = val
        session["state"] = ITR2_ASK_OTHER_INCOME
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_OTHER_INCOME"))
        return Response(status_code=200)

    if state == ITR2_ASK_OTHER_INCOME:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr2"]["other_income"] = val
        session["state"] = ITR2_ASK_STCG
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR2_ASK_STCG"))
        return Response(status_code=200)

    if state == ITR2_ASK_STCG:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr2"]["stcg_111a"] = val
        session["state"] = ITR2_ASK_LTCG
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR2_ASK_LTCG"))
        return Response(status_code=200)

    if state == ITR2_ASK_LTCG:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr2"]["ltcg_112a"] = val
        session["state"] = ITR2_ASK_80C
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_80C"))
        return Response(status_code=200)

    if state == ITR2_ASK_80C:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr2"]["sec_80c"] = val
        session["state"] = ITR2_ASK_80D
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_80D"))
        return Response(status_code=200)

    if state == ITR2_ASK_80D:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr2"]["sec_80d"] = val
        session["state"] = ITR2_ASK_TDS
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_TDS"))
        return Response(status_code=200)

    if state == ITR2_ASK_TDS:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr2"]["tds"] = val
        await send(wa_id, t(session, "ITR_COMPUTING"))
        d = session["data"]["itr2"]
        try:
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
            formatted = format_itr_result(result, lang)
            # Store result for PDF/JSON download
            session["data"]["itr_last_result"] = {
                "form_type": "ITR-2",
                "input_data": d,
                "input_type": "manual",
            }
            # Auto-create ITR draft and send to CA
            auto_ca_msg = ""
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.itr_workflow import create_itr_draft_from_session

                form_type = "ITR-2"
                async for db in _get_db():
                    draft = await create_itr_draft_from_session(wa_id, session, form_type, db)
                    if draft.status == "pending_ca_review" and draft.ca_id:
                        auto_ca_msg = "\n\n" + t(session, "ITR_AUTO_SENT_TO_CA", form_type=form_type)
                    elif draft.status == "pending_ca_review" and not draft.ca_id:
                        auto_ca_msg = "\n\n" + t(session, "ITR_QUEUED_FOR_REVIEW", form_type=form_type)
            except Exception:
                logger.exception("Auto ITR draft creation failed for %s", wa_id)
            session["state"] = ITR_FILING_DOWNLOAD
            await session_cache.save_session(wa_id, session)
            await send(
                wa_id,
                formatted + auto_ca_msg + t(session, "ITR_FILING_OPTIONS"),
            )
        except Exception:
            logger.exception("ITR-2 computation failed")
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_RESULT_ERROR"))
        return Response(status_code=200)

    # === ITR-4 FLOW: Personal Details ===
    if state == ITR4_ASK_PAN:
        pan = text.strip().upper()
        if len(pan) != 10 or not pan[:5].isalpha() or not pan[5:9].isdigit() or not pan[9].isalpha():
            await send(wa_id, t(session, "ITR_INVALID_PAN"))
            return Response(status_code=200)
        session["data"]["itr4"]["pan"] = pan
        session["state"] = ITR4_ASK_NAME
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_NAME"))
        return Response(status_code=200)

    if state == ITR4_ASK_NAME:
        name = text.strip()
        if len(name) < 2:
            await send(wa_id, t(session, "ITR_INVALID_NAME"))
            return Response(status_code=200)
        session["data"]["itr4"]["name"] = name
        session["state"] = ITR4_ASK_DOB
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_DOB"))
        return Response(status_code=200)

    if state == ITR4_ASK_DOB:
        dob = text.strip().replace("-", "/")
        parts = dob.split("/")
        valid_dob = False
        if len(parts) == 3:
            try:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                from datetime import date as _date
                _date(y, m, d)  # validate
                valid_dob = True
            except (ValueError, IndexError):
                pass
        if not valid_dob:
            await send(wa_id, t(session, "ITR_INVALID_DOB"))
            return Response(status_code=200)
        session["data"]["itr4"]["dob"] = dob
        session["state"] = ITR4_ASK_GENDER
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_GENDER"))
        return Response(status_code=200)

    if state == ITR4_ASK_GENDER:
        gender_map = {"1": "M", "2": "F", "3": "O", "m": "M", "f": "F", "o": "O",
                      "male": "M", "female": "F", "other": "O"}
        g = gender_map.get(text.strip().lower())
        if not g:
            await send(wa_id, t(session, "ITR_ASK_GENDER"))
            return Response(status_code=200)
        session["data"]["itr4"]["gender"] = g
        session["state"] = ITR4_ASK_TYPE
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR4_ASK_PROFESSION_TYPE"))
        return Response(status_code=200)

    # === ITR-4 FLOW: Business Type & Financials ===
    if state == ITR4_ASK_TYPE:
        if text == "1":
            session["data"]["itr4"]["type"] = "business"
            session["data"]["itr4"]["rate"] = 8
        elif text == "2":
            session["data"]["itr4"]["type"] = "profession"
            session["data"]["itr4"]["rate"] = 50
        else:
            await send(wa_id, t(session, "ITR4_ASK_PROFESSION_TYPE"))
            return Response(status_code=200)

        # Check for GST data to auto-populate turnover
        gst_link = get_gst_data_from_session(session, "2024-25")
        if gst_link and gst_link.total_turnover > 0:
            session["data"]["itr4"]["gst_link"] = gst_link_to_dict(gst_link)
            session["state"] = ITR4_GST_LINK_CONFIRM
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR4_GST_DATA_FOUND",
                turnover=f"{float(gst_link.total_turnover):,.0f}",
                count=gst_link.invoice_count,
                period=gst_link.period_coverage or "FY 2024-25",
            ))
        else:
            session["state"] = ITR4_ASK_TURNOVER
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ASK_TURNOVER"))
        return Response(status_code=200)

    # GST-ITR Link Confirmation for ITR-4
    if state == ITR4_GST_LINK_CONFIRM:
        gst_data = session.get("data", {}).get("itr4", {}).get("gst_link", {})
        if text == "1":
            # Use GST turnover
            turnover = float(gst_data.get("total_turnover", 0))
            session["data"]["itr4"]["turnover"] = turnover
            await send(wa_id, t(session, "ITR4_GST_DATA_LINKED",
                turnover=f"{turnover:,.0f}"))
            session["state"] = ITR4_ASK_80C
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ASK_80C"))
        elif text == "2":
            # Enter manually
            session["state"] = ITR4_ASK_TURNOVER
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_ASK_TURNOVER"))
        else:
            await send(wa_id, t(session, "ITR4_GST_DATA_FOUND",
                turnover=f"{float(gst_data.get('total_turnover', 0)):,.0f}",
                count=gst_data.get("invoice_count", 0),
                period=gst_data.get("period_coverage", "FY 2024-25"),
            ))
        return Response(status_code=200)

    if state == ITR4_ASK_TURNOVER:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr4"]["turnover"] = val
        session["state"] = ITR4_ASK_80C
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_80C"))
        return Response(status_code=200)

    if state == ITR4_ASK_80C:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr4"]["sec_80c"] = val
        session["state"] = ITR4_ASK_TDS
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "ITR_ASK_TDS"))
        return Response(status_code=200)

    if state == ITR4_ASK_TDS:
        val = _parse_number(text)
        if val is None:
            await send(wa_id, t(session, "ITR_INVALID_NUMBER"))
            return Response(status_code=200)
        session["data"]["itr4"]["tds"] = val
        await send(wa_id, t(session, "ITR_COMPUTING"))
        d = session["data"]["itr4"]
        try:
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
            formatted = format_itr_result(result, lang)
            # Store result for PDF/JSON download
            session["data"]["itr_last_result"] = {
                "form_type": "ITR-4",
                "input_data": d,
                "input_type": "manual",
            }
            # Auto-create ITR draft and send to CA
            auto_ca_msg = ""
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.itr_workflow import create_itr_draft_from_session

                form_type = "ITR-4"
                async for db in _get_db():
                    draft = await create_itr_draft_from_session(wa_id, session, form_type, db)
                    if draft.status == "pending_ca_review" and draft.ca_id:
                        auto_ca_msg = "\n\n" + t(session, "ITR_AUTO_SENT_TO_CA", form_type=form_type)
                    elif draft.status == "pending_ca_review" and not draft.ca_id:
                        auto_ca_msg = "\n\n" + t(session, "ITR_QUEUED_FOR_REVIEW", form_type=form_type)
            except Exception:
                logger.exception("Auto ITR draft creation failed for %s", wa_id)
            session["state"] = ITR_FILING_DOWNLOAD
            await session_cache.save_session(wa_id, session)
            await send(
                wa_id,
                formatted + auto_ca_msg + t(session, "ITR_FILING_OPTIONS"),
            )
        except Exception:
            logger.exception("ITR-4 computation failed")
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_RESULT_ERROR"))
        return Response(status_code=200)

    # Should never reach here
    return None
