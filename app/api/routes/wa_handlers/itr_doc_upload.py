# app/api/routes/wa_handlers/itr_doc_upload.py
"""ITR document upload flow handler.

States handled:
    ITR_DOC_TYPE_MENU, ITR_DOC_UPLOAD, ITR_DOC_REVIEW,
    ITR_DOC_EDIT_FIELD, ITR_DOC_PICK_ITR, ITR_FILING_DOWNLOAD
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Callable, Awaitable

from fastapi import Response

logger = logging.getLogger("wa_handlers.itr_doc_upload")

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------
ITR_DOC_TYPE_MENU = "ITR_DOC_TYPE_MENU"
ITR_DOC_UPLOAD = "ITR_DOC_UPLOAD"
ITR_DOC_REVIEW = "ITR_DOC_REVIEW"
ITR_DOC_EDIT_FIELD = "ITR_DOC_EDIT_FIELD"
ITR_DOC_PICK_ITR = "ITR_DOC_PICK_ITR"
ITR_FILING_DOWNLOAD = "ITR_FILING_DOWNLOAD"

MAIN_MENU = "MAIN_MENU"

HANDLED_STATES = {
    ITR_DOC_TYPE_MENU,
    ITR_DOC_UPLOAD,
    ITR_DOC_REVIEW,
    ITR_DOC_EDIT_FIELD,
    ITR_DOC_PICK_ITR,
    ITR_FILING_DOWNLOAD,
}

# Document type labels for i18n
_DOC_TYPE_LABELS = {
    "form16": "Form 16",
    "26as": "Form 26AS",
    "ais": "AIS",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_number(text: str) -> float | None:
    """Parse a number from user text, stripping commas and currency symbols."""
    cleaned = text.replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


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


async def _reconstruct_itr_computation(session: dict, form_type: str, input_type: str):
    """
    Reconstruct ITR input and computed result from session data.

    Returns (inp, result) tuple where inp is ITR1Input, ITR2Input, or ITR4Input
    and result is ITRResult.
    """
    from app.domain.services.itr_form_parser import (
        dict_to_merged,
        merged_to_itr1_input,
        merged_to_itr2_input,
        merged_to_itr4_input,
    )
    from app.domain.services.itr_service import (
        ITR1Input,
        ITR2Input,
        ITR4Input,
        compute_itr1_dynamic as compute_itr1,
        compute_itr2_dynamic as compute_itr2,
        compute_itr4_dynamic as compute_itr4,
    )

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


async def _show_main_menu(wa_id: str, session: dict, session_cache: Any, send: Callable, t: Callable) -> None:
    """Navigate to main menu."""
    session["state"] = MAIN_MENU
    session["stack"] = []
    await session_cache.save_session(wa_id, session)
    await send(wa_id, t(session, "WELCOME_MENU"))


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


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
    """Handle ITR document upload sub-flow states. Returns Response or None."""

    if state not in HANDLED_STATES:
        return None

    lang = get_lang(session) if get_lang else session.get("lang", "en")

    # --- ITR_DOC_TYPE_MENU ---
    if state == ITR_DOC_TYPE_MENU:
        doc_type_map = {"1": "form16", "2": "26as", "3": "ais"}
        if text in doc_type_map:
            doc_type = doc_type_map[text]
            session.setdefault("data", {}).setdefault("itr_docs", {})
            session["data"]["itr_docs"]["pending_type"] = doc_type
            push_state(session, ITR_DOC_TYPE_MENU)
            session["state"] = ITR_DOC_UPLOAD
            await session_cache.save_session(wa_id, session)
            label = _DOC_TYPE_LABELS.get(doc_type, doc_type)
            await send(wa_id, t(session, "ITR_DOC_UPLOAD_PROMPT", doc_type=label))
            return Response(status_code=200)
        await send(wa_id, t(session, "ITR_DOC_TYPE_MENU"))
        return Response(status_code=200)

    # --- ITR_DOC_UPLOAD ---
    if state == ITR_DOC_UPLOAD:
        # Text message in upload state — re-prompt
        await send(wa_id, t(session, "ITR_DOC_UPLOAD_PROMPT",
            doc_type=_DOC_TYPE_LABELS.get(
                session.get("data", {}).get("itr_docs", {}).get("pending_type", ""),
                "document"
            )))
        return Response(status_code=200)

    # --- ITR_DOC_REVIEW ---
    if state == ITR_DOC_REVIEW:
        from app.domain.services.itr_form_parser import (
            dict_to_merged,
            dict_to_parsed_form16,
            dict_to_parsed_form26as,
            dict_to_parsed_ais,
            format_review_summary,
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
        from app.domain.services.gst_itr_linker import get_gst_data_from_session

        if text == "1":
            # Upload another document
            push_state(session, ITR_DOC_REVIEW)
            session["state"] = ITR_DOC_TYPE_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_DOC_TYPE_MENU"))
            return Response(status_code=200)
        if text == "2":
            # Edit a field
            push_state(session, ITR_DOC_REVIEW)
            session["state"] = ITR_DOC_EDIT_FIELD
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_DOC_EDIT_PROMPT"))
            return Response(status_code=200)
        if text == "3":
            # Auto-detect ITR form from merged data, then confirm
            merged_dict = session.get("data", {}).get("itr_docs", {}).get("merged", {})
            detected_form = _detect_itr_form(merged_dict)
            push_state(session, ITR_DOC_REVIEW)
            session["state"] = ITR_DOC_PICK_ITR
            session.setdefault("data", {}).setdefault("itr_docs", {})["detected_form"] = detected_form
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_DOC_FORM_DETECTED", form_type=detected_form))
            return Response(status_code=200)
        if text == "4":
            # View Mismatches & Checklist
            merged = dict_to_merged(
                session.get("data", {}).get("itr_docs", {}).get("merged", {})
            )
            uploaded = session.get("data", {}).get("itr_docs", {}).get("uploaded", [])
            try:
                # Run mismatch detection
                form16 = None
                form26as = None
                ais = None
                if merged.raw_form16:
                    form16 = dict_to_parsed_form16(merged.raw_form16)
                if merged.raw_form26as:
                    form26as = dict_to_parsed_form26as(merged.raw_form26as)
                if merged.raw_ais:
                    ais = dict_to_parsed_ais(merged.raw_ais)

                # Get GST turnover if available
                gst_turnover = None
                gst_link = get_gst_data_from_session(session, "2024-25")
                if gst_link:
                    gst_turnover = gst_link.total_turnover

                report = detect_mismatches(form16, form26as, ais, gst_turnover)
                if report.mismatches:
                    mismatch_text = format_mismatch_report(report, lang)
                    await send(wa_id, t(session, "ITR_MISMATCH_FOUND", report=mismatch_text))
                    # Store in session for ITR draft
                    session["data"]["itr_docs"]["mismatches"] = report_to_dict(report)
                else:
                    await send(wa_id, t(session, "ITR_MISMATCH_NONE"))

                # Generate and show checklist
                checklist = generate_checklist(merged, uploaded)
                checklist_text = format_checklist(checklist, lang)
                await send(wa_id, t(session, "ITR_CHECKLIST_TITLE", checklist=checklist_text))
                session["data"]["itr_docs"]["checklist"] = checklist_to_dict(checklist)
                await session_cache.save_session(wa_id, session)
            except Exception:
                logger.exception("Mismatch/checklist failed for %s", wa_id)
                await send(wa_id, t(session, "ITR_MISMATCH_NONE"))
            return Response(status_code=200)
        # Unrecognized — re-show review
        merged = dict_to_merged(session.get("data", {}).get("itr_docs", {}).get("merged", {}))
        summary = format_review_summary(merged, lang)
        await send(wa_id, summary + t(session, "ITR_DOC_REVIEW_OPTIONS"))
        return Response(status_code=200)

    # --- ITR_DOC_EDIT_FIELD ---
    if state == ITR_DOC_EDIT_FIELD:
        from app.domain.services.itr_form_parser import (
            ITR_DOC_EDITABLE_FIELDS,
            dict_to_merged,
            merged_to_dict,
            format_review_summary,
        )

        parts = text.strip().split(None, 1)
        if len(parts) == 2:
            field_num, raw_val = parts
            if field_num in ITR_DOC_EDITABLE_FIELDS:
                val = _parse_number(raw_val)
                if val is not None:
                    attr_name, _ = ITR_DOC_EDITABLE_FIELDS[field_num]
                    merged = dict_to_merged(
                        session.get("data", {}).get("itr_docs", {}).get("merged", {})
                    )
                    setattr(merged, attr_name, Decimal(str(val)))
                    session["data"]["itr_docs"]["merged"] = merged_to_dict(merged)
                    session["state"] = ITR_DOC_REVIEW
                    await session_cache.save_session(wa_id, session)
                    summary = format_review_summary(merged, lang)
                    await send(wa_id, summary + t(session, "ITR_DOC_REVIEW_OPTIONS"))
                    return Response(status_code=200)
        # Invalid input
        await send(wa_id, t(session, "ITR_DOC_EDIT_INVALID"))
        return Response(status_code=200)

    # --- ITR_DOC_PICK_ITR ---
    if state == ITR_DOC_PICK_ITR:
        from app.domain.services.itr_form_parser import (
            dict_to_merged,
            merged_to_itr1_input,
            merged_to_itr2_input,
            merged_to_itr4_input,
        )
        from app.domain.services.itr_service import (
            compute_itr1_dynamic as compute_itr1,
            compute_itr2_dynamic as compute_itr2,
            compute_itr4_dynamic as compute_itr4,
            format_itr_result,
        )

        merged = dict_to_merged(
            session.get("data", {}).get("itr_docs", {}).get("merged", {})
        )
        detected_form = session.get("data", {}).get("itr_docs", {}).get("detected_form")
        try:
            form_type = None
            if text == "1" and detected_form:
                # Proceed with auto-detected form
                form_type = detected_form
            elif text == "2" and detected_form:
                # User wants to choose different form — show manual picker
                await send(wa_id, t(session, "ITR_DOC_PICK_ITR"))
                return Response(status_code=200)
            elif text in ("1", "2", "3") and not detected_form:
                # Manual form selection (fallback if no auto-detect)
                form_type = {"1": "ITR-1", "2": "ITR-2", "3": "ITR-4"}.get(text)
            else:
                detected = session.get("data", {}).get("itr_docs", {}).get("detected_form")
                if detected:
                    await send(wa_id, t(session, "ITR_DOC_FORM_DETECTED", form_type=detected))
                else:
                    await send(wa_id, t(session, "ITR_DOC_PICK_ITR"))
                return Response(status_code=200)

            # Compute based on selected form_type
            if form_type == "ITR-1":
                inp = merged_to_itr1_input(merged)
                result = await compute_itr1(inp)
            elif form_type == "ITR-2":
                inp = merged_to_itr2_input(merged)
                result = await compute_itr2(inp)
            else:
                inp = merged_to_itr4_input(merged)
                result = await compute_itr4(inp)
            formatted = format_itr_result(result, lang)
            # Store result for PDF/JSON download
            session["data"]["itr_last_result"] = {
                "form_type": form_type,
                "input_type": "documents",
            }
            # Auto-create ITR draft and send to CA
            auto_ca_msg = ""
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.itr_workflow import create_itr_draft_from_session

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
            logger.exception("ITR computation from documents failed")
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ITR_RESULT_ERROR"))
        return Response(status_code=200)

    # --- ITR_FILING_DOWNLOAD ---
    if state == ITR_FILING_DOWNLOAD:
        from app.domain.services.itr_pdf import generate_itr1_pdf, generate_itr4_pdf
        from app.infrastructure.external.whatsapp_client import (
            send_whatsapp_document as send_whatsapp_document_bytes,
        )

        itr_info = session.get("data", {}).get("itr_last_result", {})
        form_type = itr_info.get("form_type", "ITR-1")
        input_type = itr_info.get("input_type", "manual")

        if text == "4":
            try:
                # Reconstruct ITR computation from session
                inp, result = await _reconstruct_itr_computation(session, form_type, input_type)

                # Generate PDF
                await send(wa_id, t(session, "ITR_FILING_GENERATING", form_type=form_type))
                if form_type == "ITR-1":
                    pdf_bytes = generate_itr1_pdf(inp, result)
                elif form_type == "ITR-2":
                    # Reuse ITR-1 PDF layout (covers salary + CG breakdown)
                    pdf_bytes = generate_itr1_pdf(inp, result)
                else:
                    pdf_bytes = generate_itr4_pdf(inp, result)
                filename = f"{form_type.replace('-', '')}_computation.pdf"
                await send_whatsapp_document_bytes(
                    wa_id, pdf_bytes, filename,
                    caption=f"{form_type} Tax Computation",
                )
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
                await send(wa_id, t(session, "ITR_FILING_SENT", form_type=form_type))
            except Exception:
                logger.exception("ITR filing/download failed for %s", wa_id)
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
                await send(wa_id, t(session, "ITR_FILING_ERROR"))
            return Response(status_code=200)

        elif text == "5":
            # Check ITR status
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.repositories.itr_draft_repository import ITRDraftRepository
                from app.infrastructure.db.models import User
                from sqlalchemy import select

                async for db in _get_db():
                    stmt = select(User).where(User.whatsapp_number == wa_id)
                    res = await db.execute(stmt)
                    user = res.scalar_one_or_none()
                    if user:
                        repo = ITRDraftRepository(db)
                        drafts = await repo.get_by_user(user.id, limit=3)
                        if drafts:
                            lines = []
                            for d in drafts:
                                status_str = d.status.replace("_", " ").title()
                                ca_note = f" | CA: {d.ca_notes[:50]}..." if d.ca_notes else ""
                                lines.append(f"• {d.form_type} AY {d.assessment_year} — {status_str}{ca_note}")
                            await send(wa_id, "ITR Status:\n\n" + "\n".join(lines) + "\n\nMENU = Main Menu")
                        else:
                            await send(wa_id, t(session, "ITR_NO_DRAFTS"))
                    else:
                        await send(wa_id, t(session, "ITR_NO_DRAFTS"))
            except Exception:
                logger.exception("ITR status check failed for %s", wa_id)
                await send(wa_id, "Could not check status. Try again.\n\nMENU = Main Menu")
            return Response(status_code=200)

        if text == "0":
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await _show_main_menu(wa_id, session, session_cache, send, t)
            return Response(status_code=200)

        # Invalid input — show options again
        await send(wa_id, t(session, "ITR_FILING_OPTIONS"))
        return Response(status_code=200)

    return None
