# app/api/routes/wa_handlers/gst_compliance.py
"""GST compliance handlers — menus, filing, NIL return, composition, QRMP, annual.

States handled:
    GST_MENU, GST_FILING_MENU, GST_PERIOD_MENU, GST_UPLOAD_PURCHASE,
    NIL_FILING_MENU, NIL_FILING_CONFIRM, GST_PAYMENT_ENTRY,
    GST_COMPOSITION_MENU, GST_QRMP_MENU, GST_ANNUAL_MENU, GST_FILING_CONFIRM
"""
from __future__ import annotations
import logging
from typing import Any, Callable, Awaitable
from fastapi import Response

logger = logging.getLogger("wa_handlers.gst_compliance")

# State constants
GST_MENU = "GST_MENU"
GST_FILING_MENU = "GST_FILING_MENU"
GST_PERIOD_MENU = "GST_PERIOD_MENU"
GST_UPLOAD_PURCHASE = "GST_UPLOAD_PURCHASE"
NIL_FILING_MENU = "NIL_FILING_MENU"
NIL_FILING_CONFIRM = "NIL_FILING_CONFIRM"
GST_PAYMENT_ENTRY = "GST_PAYMENT_ENTRY"
GST_COMPOSITION_MENU = "GST_COMPOSITION_MENU"
GST_QRMP_MENU = "GST_QRMP_MENU"
GST_ANNUAL_MENU = "GST_ANNUAL_MENU"
GST_FILING_CONFIRM = "GST_FILING_CONFIRM"

# Additional states referenced in logic
WAIT_GSTIN = "WAIT_GSTIN"
SMALL_WIZARD_SALES = "SMALL_WIZARD_SALES"
MEDIUM_CREDIT_CHECK = "MEDIUM_CREDIT_CHECK"
GST_RISK_REVIEW = "GST_RISK_REVIEW"
MULTI_GSTIN_MENU = "MULTI_GSTIN_MENU"
GST_FILING_STATUS = "GST_FILING_STATUS"
REFUND_MENU = "REFUND_MENU"
NOTICE_MENU = "NOTICE_MENU"
EXPORT_MENU = "EXPORT_MENU"
EINVOICE_MENU = "EINVOICE_MENU"
EWAYBILL_MENU = "EWAYBILL_MENU"
SMART_UPLOAD = "SMART_UPLOAD"
MAIN_MENU = "MAIN_MENU"

HANDLED_STATES = {
    GST_MENU,
    GST_FILING_MENU,
    GST_PERIOD_MENU,
    GST_UPLOAD_PURCHASE,
    NIL_FILING_MENU,
    NIL_FILING_CONFIRM,
    GST_PAYMENT_ENTRY,
    GST_COMPOSITION_MENU,
    "GST_COMPOSITION_TURNOVER",
    GST_QRMP_MENU,
    GST_ANNUAL_MENU,
    GST_FILING_CONFIRM,
}


async def handle(
    state, text, wa_id, session, *,
    session_cache, send, send_buttons, send_menu_result, t,
    push_state, pop_state, state_to_screen_key, get_lang=None,
    media_id=None, download_media=None, show_main_menu=None,
    get_current_gst_period=None, prepare_gstr3b=None, format_gstr3b=None,
    aggregate_invoices=None, **_extra,
) -> Response | None:
    """
    Handle GST compliance states.

    Args:
        state: current state
        text: user text input
        wa_id: WhatsApp ID
        session: session dict
        session_cache: session cache object
        send: async func to send text
        send_buttons: async func to send buttons
        send_menu_result: async func to send menu result
        t: translation func
        push_state: func to push state to stack
        pop_state: func to pop state from stack
        state_to_screen_key: func to map state to i18n key
        get_lang: func to get session language
        media_id: WhatsApp media ID if present
        download_media: async func to download media
        show_main_menu: async func to show main menu
        get_current_gst_period: func to get current GST period
        prepare_gstr3b: func to prepare GSTR-3B summary
        format_gstr3b: func to format GSTR-3B for display
        aggregate_invoices: func to aggregate invoices
        **_extra: extra args (ignored)

    Returns:
        Response(status_code=200) if handled, None otherwise
    """
    if state not in HANDLED_STATES:
        return None

    # GST_MENU dispatcher
    if state == GST_MENU:
        from app.domain.services.whatsapp_menu_builder import resolve_gst_menu_choice, build_gst_menu
        feature_code = await resolve_gst_menu_choice(text, session)

        if feature_code == "enter_gstin":
            push_state(session, GST_MENU)
            session["state"] = WAIT_GSTIN
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "ASK_GSTIN"))
            return Response(status_code=200)

        if feature_code == "monthly_compliance":
            # Monthly Compliance — branch by taxpayer type AND segment
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "PERIOD_NO_GSTIN"))
                return Response(status_code=200)
            push_state(session, GST_MENU)

            # Determine taxpayer type and segment from BusinessClient
            taxpayer_type = "regular"
            client_segment = session.get("data", {}).get("client_segment", "small")
            bc = None
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.models import BusinessClient as BCModel
                from sqlalchemy import select as sa_select
                async for db in _get_db():
                    bc_stmt = sa_select(BCModel).where(BCModel.gstin == gstin)
                    bc_result = await db.execute(bc_stmt)
                    bc = bc_result.scalar_one_or_none()
                    if bc and bc.taxpayer_type:
                        taxpayer_type = bc.taxpayer_type
                    if bc and bc.segment:
                        client_segment = bc.segment
                    break
            except Exception:
                pass

            period = session.get("data", {}).get("gst_period") or get_current_gst_period()
            session.setdefault("data", {})["gst_period"] = period
            session.setdefault("data", {})["taxpayer_type"] = taxpayer_type

            # Small segment: guided wizard
            if client_segment == "small" and taxpayer_type == "regular":
                session["state"] = SMALL_WIZARD_SALES
                session.setdefault("data", {})["wizard_sales_invoices"] = []
                await session_cache.save_session(wa_id, session)
                await send(wa_id, t(session, "WIZARD_SALES_PROMPT"))
                return Response(status_code=200)

            # Medium segment: credit check first
            if client_segment == "medium" and taxpayer_type == "regular":
                session["state"] = MEDIUM_CREDIT_CHECK
                await session_cache.save_session(wa_id, session)
                await send(wa_id, t(session, "CREDIT_CHECK_RUNNING"))
                return Response(status_code=200)

            if taxpayer_type == "composition":
                session["state"] = GST_COMPOSITION_MENU
                await session_cache.save_session(wa_id, session)
                rate = "1.0"
                if bc and bc.composition_rate:
                    rate = str(bc.composition_rate)
                await send(wa_id, t(session, "GST_COMPOSITION_MENU",
                                          period=period, gstin=gstin, rate=rate))
            elif taxpayer_type == "qrmp":
                session["state"] = GST_QRMP_MENU
                await session_cache.save_session(wa_id, session)
                await send(wa_id, t(session, "GST_QRMP_MENU",
                                          period=period, gstin=gstin))
            else:
                session["state"] = GST_PERIOD_MENU
                await session_cache.save_session(wa_id, session)
                await send(wa_id, t(session, "GST_PERIOD_MENU",
                                          period=period, gstin=gstin, status="draft"))
            return Response(status_code=200)

        if feature_code == "nil_return":
            # NIL GST Return — one-click flow
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "NIL_FILING_NO_GSTIN"))
                return Response(status_code=200)
            period = get_current_gst_period()
            push_state(session, GST_MENU)
            session["state"] = NIL_FILING_MENU
            session.setdefault("data", {})["nil_period"] = period
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "NIL_FILING_MENU", period=period, gstin=gstin))
            return Response(status_code=200)

        if feature_code == "upload_invoices":
            # Upload & Scan Invoices (for GST)
            push_state(session, GST_MENU)
            session["state"] = SMART_UPLOAD
            session.setdefault("data", {})["smart_invoices"] = []
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "UPLOAD_SMART_PROMPT"))
            return Response(status_code=200)

        if feature_code == "e_invoice":
            # e-Invoice — enter conversational flow
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "EINVOICE_NO_GSTIN"))
                return Response(status_code=200)
            push_state(session, GST_MENU)
            session["state"] = EINVOICE_MENU
            await session_cache.save_session(wa_id, session)
            await send_buttons(
                wa_id,
                t(session, "EINVOICE_MENU"),
                [
                    {"id": "einv_generate", "title": "🧾 Generate IRN"},
                    {"id": "einv_status", "title": "📋 Check Status"},
                    {"id": "einv_cancel", "title": "❌ Cancel IRN"},
                ],
                header="e-Invoice",
            )
            return Response(status_code=200)

        if feature_code == "e_waybill":
            # e-WayBill — enter conversational flow
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "EWAYBILL_NO_GSTIN"))
                return Response(status_code=200)
            push_state(session, GST_MENU)
            session["state"] = EWAYBILL_MENU
            await session_cache.save_session(wa_id, session)
            await send_buttons(
                wa_id,
                t(session, "EWAYBILL_MENU"),
                [
                    {"id": "ewb_generate", "title": "🚛 Generate EWB"},
                    {"id": "ewb_track", "title": "📋 Track EWB"},
                    {"id": "ewb_vehicle", "title": "🚗 Update Vehicle"},
                ],
                header="e-WayBill",
            )
            return Response(status_code=200)

        if feature_code == "annual_return":
            # Annual Return (GSTR-9) menu
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "PERIOD_NO_GSTIN"))
                return Response(status_code=200)
            push_state(session, GST_MENU)
            session["state"] = GST_ANNUAL_MENU
            session.setdefault("data", {})["annual_fy"] = "2024-25"
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "GST_ANNUAL_MENU"))
            return Response(status_code=200)

        if feature_code == "risk_scoring":
            # Risk scoring review — real integration
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "PERIOD_NO_GSTIN"))
                return Response(status_code=200)
            push_state(session, GST_MENU)
            session["state"] = GST_RISK_REVIEW
            await session_cache.save_session(wa_id, session)
            # Try to fetch latest risk assessment
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.gst_explainer import format_risk_factors
                async for _db in _get_db():
                    from app.infrastructure.db.models import RiskAssessment, ReturnPeriod
                    from sqlalchemy import select
                    stmt = (
                        select(RiskAssessment)
                        .join(ReturnPeriod, ReturnPeriod.id == RiskAssessment.period_id)
                        .where(ReturnPeriod.gstin == gstin)
                        .order_by(RiskAssessment.created_at.desc())
                        .limit(1)
                    )
                    result = await _db.execute(stmt)
                    assessment = result.scalar_one_or_none()
                    if assessment:
                        factors_text = format_risk_factors(assessment)
                        await send(wa_id, t(session, "RISK_SCORE_RESULT",
                                                   gstin=gstin,
                                                   score=assessment.risk_score,
                                                   level=assessment.risk_level,
                                                   factors=factors_text))
                    else:
                        await send(wa_id, t(session, "RISK_SCORING_IN_PROGRESS"))
                    break
            except Exception:
                logger.exception("Risk scoring fetch error")
                await send(wa_id, t(session, "RISK_SCORING_IN_PROGRESS"))
            return Response(status_code=200)

        if feature_code == "multi_gstin":
            # Multi-GSTIN management — enter flow
            push_state(session, GST_MENU)
            session["state"] = MULTI_GSTIN_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "MULTI_GSTIN_MENU"))
            return Response(status_code=200)

        if feature_code == "credit_check":
            # Medium segment credit check
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "PERIOD_NO_GSTIN"))
                return Response(status_code=200)
            push_state(session, GST_MENU)
            session["state"] = MEDIUM_CREDIT_CHECK
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "CREDIT_CHECK_RUNNING"))
            return Response(status_code=200)

        if feature_code == "filing_status":
            # Filing status check
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "PERIOD_NO_GSTIN"))
                return Response(status_code=200)
            push_state(session, GST_MENU)
            session["state"] = GST_FILING_STATUS
            await session_cache.save_session(wa_id, session)
            # Show filing status for current period
            period = get_current_gst_period()
            await send(wa_id, f"📋 Filing Status for {gstin}\nPeriod: {period}\n\nChecking status...\n\nMENU = Main Menu\nBACK = Go Back")
            return Response(status_code=200)

        if feature_code == "refund_tracking":
            # Refund tracking
            push_state(session, GST_MENU)
            session["state"] = REFUND_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "REFUND_MENU"))
            return Response(status_code=200)

        if feature_code == "notice_mgmt":
            # Notice management
            push_state(session, GST_MENU)
            session["state"] = NOTICE_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "NOTICE_MENU"))
            return Response(status_code=200)

        if feature_code == "export_services":
            # Export services
            push_state(session, GST_MENU)
            session["state"] = EXPORT_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, "📦 Export Services\n\n1) LUT (Letter of Undertaking)\n2) Export Invoice\n3) Bond/BG Tracking\n\nMENU = Main Menu\nBACK = Go Back")
            return Response(status_code=200)

        # Invalid choice or no menu_map — re-show dynamic GST menu
        try:
            from app.core.db import get_db as _get_db
            async for _db in _get_db():
                menu_result = await build_gst_menu(wa_id, session, _db)
                break
        except Exception:
            menu_result = t(session, "GST_SERVICES")
        await session_cache.save_session(wa_id, session)
        await send_menu_result(wa_id, menu_result)
        return Response(status_code=200)

    # GST_FILING_MENU
    if state == GST_FILING_MENU:
        if text == "3":
            # NIL filing shortcut from filing menu
            gstin = session.get("data", {}).get("gstin")
            if not gstin:
                await send(wa_id, t(session, "NIL_FILING_NO_GSTIN"))
                return Response(status_code=200)
            period = get_current_gst_period()
            push_state(session, GST_FILING_MENU)
            session["state"] = NIL_FILING_MENU
            session.setdefault("data", {})["nil_period"] = period
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "NIL_FILING_MENU", period=period, gstin=gstin))
            return Response(status_code=200)

        invoices = session.get("data", {}).get("uploaded_invoices", [])
        if not invoices:
            await send(wa_id, t(session, "GST_NO_INVOICES"))
            return Response(status_code=200)
        gstin = session.get("data", {}).get("gstin", "")
        period = get_current_gst_period()
        if text == "1":
            await send(wa_id, t(session, "GST_COMPUTING"))
            summary = prepare_gstr3b(invoices)
            preview = format_gstr3b(summary)
            session["data"]["gst_filing_form"] = "GSTR-3B"
            push_state(session, GST_FILING_MENU)
            session["state"] = GST_FILING_CONFIRM
            await session_cache.save_session(wa_id, session)
            await send(wa_id, preview + "\n\n" + t(
                session, "GST_FILING_CONFIRM",
                form_type="GSTR-3B", period=period, gstin=gstin,
            ))
            return Response(status_code=200)
        if text == "2":
            summary = aggregate_invoices(invoices)
            lines = [
                "--- GSTR-1 Preview ---",
                "",
                f"Total Invoices: {summary.total_invoices}",
                f"B2B Invoices: {summary.b2b_count}",
                f"B2C Invoices: {summary.b2c_count}",
                f"Total Taxable: Rs {summary.total_taxable_value:,.0f}",
                f"Total Tax: Rs {summary.total_tax:,.0f}",
                f"Total Value: Rs {summary.total_amount:,.0f}",
            ]
            preview = "\n".join(lines)
            session["data"]["gst_filing_form"] = "GSTR-1"
            push_state(session, GST_FILING_MENU)
            session["state"] = GST_FILING_CONFIRM
            await session_cache.save_session(wa_id, session)
            await send(wa_id, preview + "\n\n" + t(
                session, "GST_FILING_CONFIRM",
                form_type="GSTR-1", period=period, gstin=gstin,
            ))
            return Response(status_code=200)
        await send(wa_id, t(session, "GST_FILING_MENU"))
        return Response(status_code=200)

    # GST_PERIOD_MENU — Monthly compliance menu
    if state == GST_PERIOD_MENU:
        gstin = session.get("data", {}).get("gstin", "")
        period = session.get("data", {}).get("gst_period", get_current_gst_period())
        lang = get_lang(session) if get_lang else session.get("lang", "en")

        if text == "1":
            # Upload Sales Invoices → existing SMART_UPLOAD (direction=outward)
            push_state(session, GST_PERIOD_MENU)
            session["state"] = SMART_UPLOAD
            session.setdefault("data", {})["smart_invoices"] = []
            session["data"]["upload_direction"] = "outward"
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "UPLOAD_SMART_PROMPT"))
            return Response(status_code=200)

        if text == "2":
            # Upload Purchase Invoices (direction=inward)
            push_state(session, GST_PERIOD_MENU)
            session["state"] = GST_UPLOAD_PURCHASE
            session.setdefault("data", {})["purchase_invoices"] = []
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "GST_UPLOAD_PURCHASE_PROMPT"))
            return Response(status_code=200)

        if text == "3":
            # Import GSTR-2B
            await send(wa_id, t(session, "GST_2B_IMPORTING", period=period))
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

                        from app.domain.services.gstr2b_service import import_gstr2b
                        result = await import_gstr2b(
                            user_id=user.id, gstin=gstin,
                            period=period, period_id=rp.id, db=db,
                        )
                        await send(wa_id, t(session, "GST_2B_IMPORTED",
                                                  period=result.period,
                                                  total_entries=result.total_entries,
                                                  supplier_count=result.supplier_count,
                                                  total_taxable=f"{result.total_taxable:,.2f}"))
                    else:
                        await send(wa_id, t(session, "PERIOD_NO_GSTIN"))
            except Exception as e:
                logger.exception("GSTR-2B import failed for %s", wa_id)
                await send(wa_id, t(session, "GST_2B_IMPORT_ERROR", error=str(e)[:100]))
            return Response(status_code=200)

        if text == "4":
            # Reconcile ITC
            await send(wa_id, t(session, "GST_RECON_RUNNING", period=period))
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

                        from app.domain.services.gst_reconciliation import reconcile_period
                        summary = await reconcile_period(rp.id, db)

                        await send(wa_id, t(session, "GST_RECON_RESULT",
                                                  period=period,
                                                  matched=summary.matched,
                                                  value_mismatch=summary.value_mismatch,
                                                  missing_in_2b=summary.missing_in_2b,
                                                  missing_in_books=summary.missing_in_books,
                                                  matched_taxable=f"{summary.matched_taxable:,.2f}"))
                    else:
                        await send(wa_id, t(session, "PERIOD_NO_GSTIN"))
            except Exception as e:
                logger.exception("Reconciliation failed for %s", wa_id)
                await send(wa_id, f"Reconciliation error: {str(e)[:100]}")
            return Response(status_code=200)

        if text == "5":
            # Compute Liability
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                comp = None
                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        rp_repo = ReturnPeriodRepository(db)
                        rp = await rp_repo.create_or_get(user.id, gstin, period)

                        from app.domain.services.gst_liability import compute_net_liability
                        comp = await compute_net_liability(rp.id, db)
                    else:
                        await send(wa_id, t(session, "PERIOD_NO_GSTIN"))

                if comp:
                    risk_text = ""
                    if comp.risk_flags:
                        risk_text = "Risk Flags: " + ", ".join(comp.risk_flags) + "\n\n"

                    await send(wa_id, t(session, "GST_LIABILITY_RESULT",
                                          period=period,
                                          output_igst=f"{comp.output_igst:,.2f}",
                                          output_cgst=f"{comp.output_cgst:,.2f}",
                                          output_sgst=f"{comp.output_sgst:,.2f}",
                                          itc_igst=f"{comp.itc_igst:,.2f}",
                                          itc_cgst=f"{comp.itc_cgst:,.2f}",
                                          itc_sgst=f"{comp.itc_sgst:,.2f}",
                                          net_igst=f"{comp.net_igst:,.2f}",
                                          net_cgst=f"{comp.net_cgst:,.2f}",
                                          net_sgst=f"{comp.net_sgst:,.2f}",
                                          total_net=f"{comp.total_net_payable:,.2f}",
                                          risk_flags=risk_text))

                    # Phase 2: Show risk score summary after liability
                    try:
                        async for db2 in _get_db():
                            from app.infrastructure.db.repositories.risk_assessment_repository import RiskAssessmentRepository
                            ra_repo = RiskAssessmentRepository(db2)
                            ra = await ra_repo.get_by_period(rp.id)
                            if ra:
                                await send(wa_id, t(session, "GST_RISK_SCORE_RESULT",
                                    period=period,
                                    score=ra.risk_score,
                                    level=ra.risk_level,
                                    cat_a=ra.category_a_score,
                                    cat_b=ra.category_b_score,
                                    cat_c=ra.category_c_score,
                                    cat_d=ra.category_d_score,
                                    cat_e=ra.category_e_score,
                                    flag_count=len(ra.risk_flags.split('"code"')) - 1 if ra.risk_flags else 0,
                                    flags_summary=f"Level: {ra.risk_level}"))
                            break
                    except Exception:
                        pass

                    # Phase 2: If net payable > 0, prompt for payment
                    if comp.total_net_payable > 0:
                        session["state"] = GST_PAYMENT_ENTRY
                        session.setdefault("data", {})["period_id"] = str(rp.id)
                        await session_cache.save_session(wa_id, session)
                        await send(wa_id, t(session, "GST_PAYMENT_PROMPT",
                                                  period=period,
                                                  net_payable=f"{comp.total_net_payable:,.2f}"))
            except Exception as e:
                logger.exception("Liability computation failed for %s", wa_id)
                await send(wa_id, f"Liability computation error: {str(e)[:100]}")
            return Response(status_code=200)

        if text == "6":
            # File GST Return → existing GST_FILING_MENU
            push_state(session, GST_PERIOD_MENU)
            session["state"] = GST_FILING_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "GST_FILING_MENU"))
            return Response(status_code=200)

        # Default: re-show period menu
        await send(wa_id, t(session, "GST_PERIOD_MENU",
                                  period=period, gstin=gstin, status="draft"))
        return Response(status_code=200)

    # GST_UPLOAD_PURCHASE — Purchase invoice upload
    if state == GST_UPLOAD_PURCHASE:
        if text and text.lower() == "done":
            # Save purchase invoices and go back to period menu
            purchase_invoices = session.get("data", {}).get("purchase_invoices", [])
            count = len(purchase_invoices)
            gstin = session.get("data", {}).get("gstin", "")
            period = session.get("data", {}).get("gst_period", get_current_gst_period())
            session["state"] = GST_PERIOD_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id,
                            f"Uploaded {count} purchase invoice(s).\n\n"
                            + t(session, "GST_PERIOD_MENU",
                                 period=period, gstin=gstin, status="draft"))
            return Response(status_code=200)

        # Process image/document upload for purchase invoices
        if media_id:
            try:
                image_bytes = await download_media(media_id)
                if image_bytes:
                    from app.domain.services.invoice_parser import parse_invoice_image
                    parsed = await parse_invoice_image(image_bytes)
                    if parsed:
                        inv_dict = {
                            "supplier_gstin": parsed.supplier_gstin,
                            "invoice_number": parsed.invoice_number,
                            "invoice_date": str(parsed.invoice_date) if parsed.invoice_date else None,
                            "taxable_value": float(parsed.taxable_value) if parsed.taxable_value else 0,
                            "tax_amount": float(parsed.tax_amount) if parsed.tax_amount else 0,
                            "cgst_amount": float(parsed.cgst_amount) if parsed.cgst_amount else 0,
                            "sgst_amount": float(parsed.sgst_amount) if parsed.sgst_amount else 0,
                            "igst_amount": float(parsed.igst_amount) if parsed.igst_amount else 0,
                            "direction": "inward",
                        }
                        session.setdefault("data", {}).setdefault("purchase_invoices", []).append(inv_dict)

                        # Save to DB as inward invoice
                        from app.core.db import get_db as _get_db
                        from sqlalchemy import select as sa_select
                        from app.infrastructure.db.models import User as UserModel
                        from app.infrastructure.db.repositories import InvoiceRepository

                        async for db in _get_db():
                            user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                            user_result = await db.execute(user_stmt)
                            user = user_result.scalar_one_or_none()
                            if user:
                                inv_repo = InvoiceRepository(db)
                                await inv_repo.create_from_parsed(
                                    user.id, parsed,
                                    direction="inward",
                                    itc_eligible=True,
                                )

                        await session_cache.save_session(wa_id, session)
                        count = len(session["data"]["purchase_invoices"])
                        await send(wa_id,
                                        f"Purchase invoice #{count} scanned.\n"
                                        f"Supplier: {parsed.supplier_gstin or 'N/A'}\n"
                                        f"Amount: Rs {parsed.taxable_value or 0}\n\n"
                                        "Send more images, or type 'done' when finished.")
                    else:
                        await send(wa_id, "Could not parse invoice. Try a clearer image, or type 'done'.")
            except Exception:
                logger.exception("Purchase invoice parse error for %s", wa_id)
                await send(wa_id, "Error processing image. Try again or type 'done'.")
            return Response(status_code=200)

        await send(wa_id, t(session, "GST_UPLOAD_PURCHASE_PROMPT"))
        return Response(status_code=200)

    # NIL_FILING_MENU
    if state == NIL_FILING_MENU:
        gstin = session.get("data", {}).get("gstin", "")
        period = session.get("data", {}).get("nil_period", get_current_gst_period())
        if text in ("1", "2", "3"):
            # Determine which forms to file
            if text == "1":
                form_type = "GSTR-3B"
            elif text == "2":
                form_type = "GSTR-1"
            else:
                form_type = "GSTR-3B + GSTR-1"
            session["data"]["nil_form_type"] = form_type
            session["state"] = NIL_FILING_CONFIRM
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(
                session, "NIL_FILING_CONFIRM",
                form_type=form_type, period=period, gstin=gstin,
            ))
            return Response(status_code=200)
        await send(wa_id, t(session, "NIL_FILING_MENU", period=period, gstin=gstin))
        return Response(status_code=200)

    # NIL_FILING_CONFIRM
    if state == NIL_FILING_CONFIRM:
        if text.upper() == "YES":
            gstin = session.get("data", {}).get("gstin", "")
            period = session.get("data", {}).get("nil_period", "")
            form_type = session.get("data", {}).get("nil_form_type", "GSTR-3B")
            if not period:
                period = get_current_gst_period()

            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.gst_workflow import create_gst_draft_from_session

                async for db in _get_db():
                    filing = await create_gst_draft_from_session(
                        wa_id, session, form_type, db, is_nil=True
                    )
                    if filing.ca_id:
                        await send(wa_id, t(session, "GST_SENT_TO_CA",
                            form_type=form_type, period=period))
                    else:
                        await send(wa_id, t(session, "GST_QUEUED_FOR_REVIEW",
                            form_type=form_type, period=period))

                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
            except ValueError as ve:
                if "CA" in str(ve) or "not found" in str(ve):
                    await send(wa_id, t(session, "GST_QUEUED_FOR_REVIEW",
                        form_type=form_type, period=period))
                else:
                    logger.exception("NIL draft creation failed for %s", wa_id)
                    await send(wa_id, t(session, "GST_FILING_ERROR"))
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
            except Exception:
                logger.exception("NIL draft creation failed for %s", wa_id)
                await send(wa_id, t(session, "GST_FILING_ERROR"))
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
            return Response(status_code=200)
        else:
            # User did not confirm — go back to NIL filing menu
            gstin = session.get("data", {}).get("gstin", "")
            period = session.get("data", {}).get("nil_period", get_current_gst_period())
            session["state"] = NIL_FILING_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "NIL_FILING_MENU", period=period, gstin=gstin))
            return Response(status_code=200)

    # GST_PAYMENT_ENTRY
    if state == GST_PAYMENT_ENTRY:
        # Expect format: <challan_number> <amount>  OR  "skip"
        gstin = session.get("data", {}).get("gstin", "")
        period = session.get("data", {}).get("gst_period", get_current_gst_period())
        period_id_str = session.get("data", {}).get("period_id")

        if text.lower() == "skip":
            session["state"] = GST_PERIOD_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "GST_PERIOD_MENU",
                                      period=period, gstin=gstin, status="data_ready"))
            return Response(status_code=200)

        # Parse challan input: "CHL001 25000" or "CHL001 10000 8000 7000"
        parts = text.strip().split()
        if len(parts) < 2:
            await send(wa_id,
                            "Please enter challan details in format:\n"
                            "<challan_number> <total_amount>\n"
                            "Example: CHL001 25000\n\n"
                            "Or type 'skip' to continue without recording payment.")
            return Response(status_code=200)

        challan_number = parts[0]
        try:
            total_amount = float(parts[1])
        except ValueError:
            await send(wa_id, "Invalid amount. Please enter a number.\nExample: CHL001 25000")
            return Response(status_code=200)

        try:
            from app.core.db import get_db as _get_db
            from app.domain.services.gst_payment import record_payment, validate_payment
            from uuid import UUID

            pid = UUID(period_id_str) if period_id_str else None
            if not pid:
                await send(wa_id, "No period found for payment recording.")
                session["state"] = GST_PERIOD_MENU
                await session_cache.save_session(wa_id, session)
                return Response(status_code=200)

            challan_data = {
                "challan_number": challan_number,
                "total": total_amount,
                "payment_mode": "online",
                "status": "confirmed",
            }

            async for db in _get_db():
                payment = await record_payment(pid, challan_data, db)
                validation = await validate_payment(pid, db)
                break

            await send(wa_id, t(session, "GST_PAYMENT_RECORDED",
                                      challan=challan_number,
                                      amount=f"{total_amount:,.2f}",
                                      period=period))

            if validation and not validation.is_fully_paid:
                await send(wa_id, t(session, "GST_PAYMENT_SHORT",
                                          shortfall=f"{validation.shortfall_total:,.2f}",
                                          period=period))
            elif validation and validation.is_fully_paid:
                await send(wa_id, t(session, "GST_PAYMENT_VALIDATED",
                                          period=period,
                                          total_paid=f"{validation.paid_total:,.2f}"))

        except Exception as e:
            logger.exception("Payment recording failed for %s", wa_id)
            await send(wa_id, f"Payment recording error: {str(e)[:100]}")

        session["state"] = GST_PERIOD_MENU
        await session_cache.save_session(wa_id, session)
        return Response(status_code=200)

    # GST_COMPOSITION_MENU
    if state == GST_COMPOSITION_MENU:
        gstin = session.get("data", {}).get("gstin", "")
        period = session.get("data", {}).get("gst_period", get_current_gst_period())

        if text == "1":
            # Enter Turnover — prompt for quarterly turnover
            session["state"] = "GST_COMPOSITION_TURNOVER"
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "GST_COMPOSITION_TURNOVER_PROMPT",
                                      period=period, gstin=gstin))
            return Response(status_code=200)

        if text == "2":
            # Compute Tax — run composition liability computation
            await send(wa_id, "Computing composition tax...")
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
                from app.domain.services.gst_composition import compute_composition_liability
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        rp_repo = ReturnPeriodRepository(db)
                        rp = await rp_repo.create_or_get(user.id, gstin, period)
                        comp = await compute_composition_liability(rp.id, db)
                        await send(wa_id, t(session, "GST_CMP08_RESULT",
                                                  period=period,
                                                  turnover=f"{comp.turnover:,.2f}",
                                                  rate=f"{comp.composition_rate:.1f}",
                                                  cgst=f"{comp.cgst:,.2f}",
                                                  sgst=f"{comp.sgst:,.2f}",
                                                  total_tax=f"{comp.tax_amount:,.2f}"))
                        session.setdefault("data", {})["period_id"] = str(rp.id)

                        # If tax > 0, prompt for payment
                        if comp.tax_amount > 0:
                            session["state"] = GST_PAYMENT_ENTRY
                            await session_cache.save_session(wa_id, session)
                            await send(wa_id, t(session, "GST_PAYMENT_PROMPT",
                                                      period=period,
                                                      net_payable=f"{comp.tax_amount:,.2f}"))
                            return Response(status_code=200)
                    else:
                        await send(wa_id, "User not found. Please register first.")
                    break
            except Exception as e:
                logger.exception("Composition computation failed for %s", wa_id)
                await send(wa_id, f"Computation error: {str(e)[:100]}")

            await session_cache.save_session(wa_id, session)
            return Response(status_code=200)

        if text == "3":
            # File CMP-08 — prepare and queue for filing
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
                from app.domain.services.gst_composition import prepare_cmp08
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        rp_repo = ReturnPeriodRepository(db)
                        rp = await rp_repo.create_or_get(user.id, gstin, period)
                        cmp08 = await prepare_cmp08(rp.id, db)
                        await send(wa_id,
                                        f"CMP-08 prepared for {period}:\n"
                                        f"Turnover: Rs {cmp08.get('total_turnover', 0):,.2f}\n"
                                        f"Tax payable: Rs {cmp08.get('total_tax', 0):,.2f}\n\n"
                                        "CMP-08 has been queued for CA review.\n\nMENU = Main Menu")
                    break
            except Exception as e:
                logger.exception("CMP-08 preparation failed for %s", wa_id)
                await send(wa_id, f"CMP-08 error: {str(e)[:100]}")

            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            return Response(status_code=200)

        if text == "0":
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await show_main_menu(wa_id, session)
            return Response(status_code=200)

        # Default: re-show composition menu
        rate = session.get("data", {}).get("composition_rate", "1.0")
        await send(wa_id, t(session, "GST_COMPOSITION_MENU",
                                  period=period, gstin=gstin, rate=rate))
        return Response(status_code=200)

    # GST_COMPOSITION_TURNOVER
    if state == "GST_COMPOSITION_TURNOVER":
        gstin = session.get("data", {}).get("gstin", "")
        period = session.get("data", {}).get("gst_period", get_current_gst_period())

        try:
            turnover = float(text.replace(",", "").strip())
        except ValueError:
            await send(wa_id, "Please enter a valid turnover amount (e.g., 500000).")
            return Response(status_code=200)

        # Save outward invoices with total turnover for the period
        try:
            from app.core.db import get_db as _get_db
            from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
            from app.infrastructure.db.repositories.invoice_repository import InvoiceRepository
            from sqlalchemy import select as sa_select
            from app.infrastructure.db.models import User as UserModel
            import datetime

            async for db in _get_db():
                user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                user_result = await db.execute(user_stmt)
                user = user_result.scalar_one_or_none()
                if user:
                    rp_repo = ReturnPeriodRepository(db)
                    rp = await rp_repo.create_or_get(user.id, gstin, period)
                    # Store turnover in computation_json
                    await rp_repo.update_computation(rp.id, {
                        "outward_taxable_turnover": turnover,
                    })
                    await send(wa_id,
                                    f"Turnover of Rs {turnover:,.2f} recorded for {period}.\n\n"
                                    "Now select option 2 (Compute Tax) from the menu.")
                break
        except Exception as e:
            logger.exception("Composition turnover save failed for %s", wa_id)
            await send(wa_id, f"Error saving turnover: {str(e)[:100]}")

        session["state"] = GST_COMPOSITION_MENU
        rate = session.get("data", {}).get("composition_rate", "1.0")
        await session_cache.save_session(wa_id, session)
        await send(wa_id, t(session, "GST_COMPOSITION_MENU",
                                  period=period, gstin=gstin, rate=rate))
        return Response(status_code=200)

    # GST_QRMP_MENU
    if state == GST_QRMP_MENU:
        gstin = session.get("data", {}).get("gstin", "")
        period = session.get("data", {}).get("gst_period", get_current_gst_period())

        if text == "1":
            # Monthly Payment — compute and show options
            await send(wa_id, "Computing monthly payment options...")
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
                from app.domain.services.gst_qrmp import compute_monthly_payment
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        rp_repo = ReturnPeriodRepository(db)
                        rp = await rp_repo.create_or_get(user.id, gstin, period)
                        payment_opts = await compute_monthly_payment(rp.id, db)
                        session.setdefault("data", {})["period_id"] = str(rp.id)

                        await send(wa_id, t(session, "GST_QRMP_MONTHLY_PAYMENT",
                                                  period=period,
                                                  method1=f"{payment_opts.method1_amount:,.2f}",
                                                  method2=f"{payment_opts.method2_amount:,.2f}"))

                        # Prompt for payment entry
                        session["state"] = GST_PAYMENT_ENTRY
                        await session_cache.save_session(wa_id, session)
                        await send(wa_id, t(session, "GST_PAYMENT_PROMPT",
                                                  period=period,
                                                  net_payable=f"{payment_opts.method1_amount:,.2f}"))
                        return Response(status_code=200)
                    else:
                        await send(wa_id, "User not found. Please register first.")
                    break
            except Exception as e:
                logger.exception("QRMP monthly payment computation failed for %s", wa_id)
                await send(wa_id, f"Computation error: {str(e)[:100]}")

            await session_cache.save_session(wa_id, session)
            return Response(status_code=200)

        if text == "2":
            # Quarterly Filing — aggregate and show
            await send(wa_id, "Computing quarterly liability...")
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.gst_qrmp import compute_quarterly_liability, is_quarter_end
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                if not is_quarter_end(period):
                    await send(wa_id,
                                    f"{period} is not a quarter-end month.\n"
                                    "Quarterly filing is only for months 3, 6, 9, 12.\n"
                                    "Use option 1 for monthly payment instead.")
                    return Response(status_code=200)

                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        ql = await compute_quarterly_liability(user.id, gstin, period, db)
                        await send(wa_id, t(session, "GST_QRMP_QUARTERLY_FILING",
                                                  period=period,
                                                  total_output=f"{ql.output_igst + ql.output_cgst + ql.output_sgst:,.2f}",
                                                  total_itc=f"{ql.itc_igst + ql.itc_cgst + ql.itc_sgst:,.2f}",
                                                  monthly_paid=f"{ql.monthly_payments_total:,.2f}",
                                                  net_payable=f"{ql.remaining_payable:,.2f}"))
                    break
            except Exception as e:
                logger.exception("QRMP quarterly computation failed for %s", wa_id)
                await send(wa_id, f"Computation error: {str(e)[:100]}")
            return Response(status_code=200)

        if text == "3":
            # IFF (Invoice Furnishing Facility)
            try:
                from app.core.db import get_db as _get_db
                from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository
                from app.domain.services.gst_qrmp import prepare_iff
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        rp_repo = ReturnPeriodRepository(db)
                        rp = await rp_repo.create_or_get(user.id, gstin, period)
                        iff_data = await prepare_iff(rp.id, db)
                        inv_count = iff_data.get("b2b_invoice_count", 0)
                        total_val = iff_data.get("total_taxable_value", 0)
                        await send(wa_id,
                                        f"IFF Summary for {period}:\n"
                                        f"B2B Invoices: {inv_count}\n"
                                        f"Total Taxable Value: Rs {total_val:,.2f}\n\n"
                                        "IFF data is ready for upload to GST portal.\n\nMENU = Main Menu")
                    break
            except Exception as e:
                logger.exception("IFF preparation failed for %s", wa_id)
                await send(wa_id, f"IFF error: {str(e)[:100]}")
            return Response(status_code=200)

        if text == "0":
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await show_main_menu(wa_id, session)
            return Response(status_code=200)

        # Default: re-show QRMP menu
        await send(wa_id, t(session, "GST_QRMP_MENU",
                                  period=period, gstin=gstin))
        return Response(status_code=200)

    # GST_ANNUAL_MENU
    if state == GST_ANNUAL_MENU:
        gstin = session.get("data", {}).get("gstin", "")

        if text == "1":
            # Aggregate Annual Return
            await send(wa_id, "Aggregating annual return data...")
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.gst_annual import aggregate_annual
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                fy = session.get("data", {}).get("annual_fy", "2024-25")
                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        annual_data = await aggregate_annual(user.id, gstin, fy, db)
                        missing_str = ", ".join(annual_data.missing_periods) if annual_data.missing_periods else "None"
                        books_diff = annual_data.books_vs_gst_diff.get("outward_diff", 0)
                        await send(wa_id, t(session, "GST_ANNUAL_SUMMARY",
                                                  fy=fy,
                                                  outward=f"{annual_data.total_outward_taxable:,.2f}",
                                                  itc=f"{annual_data.total_itc_claimed:,.2f}",
                                                  tax_paid=f"{annual_data.total_tax_paid:,.2f}",
                                                  periods=annual_data.period_count,
                                                  missing=missing_str,
                                                  diff=f"{books_diff:,.2f}"))
                        if annual_data.monthly_vs_annual_diff:
                            disc_lines = []
                            for d in annual_data.monthly_vs_annual_diff[:5]:
                                period_label = d.get("period", "?")
                                diff_pct = d.get("deviation_pct", 0)
                                disc_lines.append(f"• {period_label}: {diff_pct:.1f}% deviation")
                            await send(wa_id, t(session, "GST_ANNUAL_DISCREPANCY",
                                                      fy=fy,
                                                      discrepancies="\n".join(disc_lines)))
                    break
            except Exception as e:
                logger.exception("Annual aggregation failed for %s", wa_id)
                await send(wa_id, f"Aggregation error: {str(e)[:100]}")
            return Response(status_code=200)

        if text == "2":
            # ITC Summary
            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.gst_annual import compute_annual_itc_summary
                from sqlalchemy import select as sa_select
                from app.infrastructure.db.models import User as UserModel

                fy = session.get("data", {}).get("annual_fy", "2024-25")
                async for db in _get_db():
                    user_stmt = sa_select(UserModel).where(UserModel.whatsapp_number == wa_id)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    if user:
                        itc = await compute_annual_itc_summary(user.id, fy, db)
                        await send(wa_id,
                                        f"ITC Summary for FY {fy}:\n"
                                        f"IGST: Rs {itc.get('itc_igst', 0):,.2f}\n"
                                        f"CGST: Rs {itc.get('itc_cgst', 0):,.2f}\n"
                                        f"SGST: Rs {itc.get('itc_sgst', 0):,.2f}\n"
                                        f"Total: Rs {itc.get('itc_total', 0):,.2f}\n"
                                        f"Reversed: Rs {itc.get('itc_reversed', 0):,.2f}\n"
                                        f"Net ITC: Rs {itc.get('net_itc', 0):,.2f}\n\n"
                                        "MENU = Main Menu")
                    break
            except Exception as e:
                logger.exception("ITC summary failed for %s", wa_id)
                await send(wa_id, f"ITC summary error: {str(e)[:100]}")
            return Response(status_code=200)

        if text == "0":
            session["state"] = MAIN_MENU
            await session_cache.save_session(wa_id, session)
            await show_main_menu(wa_id, session)
            return Response(status_code=200)

        # Default: re-show annual menu
        await send(wa_id, t(session, "GST_ANNUAL_MENU"))
        return Response(status_code=200)

    # GST_FILING_CONFIRM
    if state == GST_FILING_CONFIRM:
        if text.upper() == "YES":
            gstin = session.get("data", {}).get("gstin", "")
            gst_form = session.get("data", {}).get("gst_filing_form", "GSTR-3B")
            period = get_current_gst_period()

            try:
                from app.core.db import get_db as _get_db
                from app.domain.services.gst_workflow import create_gst_draft_from_session

                async for db in _get_db():
                    filing = await create_gst_draft_from_session(
                        wa_id, session, gst_form, db
                    )
                    if filing.ca_id:
                        await send(wa_id, t(session, "GST_SENT_TO_CA",
                            form_type=gst_form, period=period))
                    else:
                        await send(wa_id, t(session, "GST_QUEUED_FOR_REVIEW",
                            form_type=gst_form, period=period))

                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
            except ValueError as ve:
                if "CA" in str(ve) or "not found" in str(ve):
                    await send(wa_id, t(session, "GST_QUEUED_FOR_REVIEW",
                        form_type=gst_form, period=period))
                else:
                    logger.exception("GST draft creation failed for %s", wa_id)
                    await send(wa_id, t(session, "GST_FILING_ERROR"))
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
            except Exception:
                logger.exception("GST draft creation failed for %s", wa_id)
                await send(wa_id, t(session, "GST_FILING_ERROR"))
                session["state"] = MAIN_MENU
                await session_cache.save_session(wa_id, session)
            return Response(status_code=200)
        else:
            session["state"] = GST_FILING_MENU
            await session_cache.save_session(wa_id, session)
            await send(wa_id, t(session, "GST_FILING_MENU"))
            return Response(status_code=200)

    return None
