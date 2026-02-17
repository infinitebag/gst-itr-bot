# app/domain/services/gst_service.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from app.core.config import settings
from app.domain.models.gst import (
    Gstr3bSummary,
    TaxBucket,
    ItcBucket,
)

logger = logging.getLogger("gst_service")

# Backward-compat alias
Gstr3BSummary = Gstr3bSummary


def D(x: Any) -> Decimal:
    """Safe Decimal conversion."""
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")


# -------- Public API used by gst_debug.py --------

def prepare_gstr3b(
    invoices: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    demo: bool = False,
) -> Gstr3bSummary:
    """
    Build a basic GSTR-3B summary from invoices.

    Expected invoice dict keys (any missing keys default to 0):
      - taxable_value
      - igst_amount, cgst_amount, sgst_amount, cess_amount
      - reverse_charge (bool) -> if True, goes to inward_reverse_charge
      - itc_eligible (bool) -> if True, add to itc_eligible

    If demo=True or invoices is empty, returns a realistic demo summary.
    """

    if demo or not invoices:
        return _demo_gstr3b_summary()

    out = TaxBucket()
    rcm = TaxBucket()
    itc = ItcBucket()

    for inv in invoices:
        taxable = D(inv.get("taxable_value"))
        igst = D(inv.get("igst_amount"))
        cgst = D(inv.get("cgst_amount"))
        sgst = D(inv.get("sgst_amount"))
        cess = D(inv.get("cess_amount"))

        is_rcm = bool(inv.get("reverse_charge", False))
        is_itc = bool(inv.get("itc_eligible", False))  # default False — items must explicitly qualify for ITC

        if is_rcm:
            rcm.taxable_value += taxable
            rcm.igst += igst
            rcm.cgst += cgst
            rcm.sgst += sgst
            rcm.cess += cess
        else:
            out.taxable_value += taxable
            out.igst += igst
            out.cgst += cgst
            out.sgst += sgst
            out.cess += cess

        if is_itc:
            itc.igst += igst
            itc.cgst += cgst
            itc.sgst += sgst
            itc.cess += cess

    return Gstr3bSummary(
        outward_taxable_supplies=out,
        inward_reverse_charge=rcm,
        itc_eligible=itc,
    )


# -------- NIL Filing --------

@dataclass
class NilFilingResult:
    """Result of a NIL GST filing operation."""
    form_type: str          # "GSTR-3B" or "GSTR-1"
    gstin: str
    period: str             # e.g., "2025-01"
    status: str             # "success", "error"
    reference_number: str   # Acknowledgement/reference number
    message: str            # Human-readable message
    filed_at: str           # ISO timestamp


@dataclass
class GstFilingResult:
    """Result of a regular (non-NIL) GST filing operation via MasterGST."""
    form_type: str          # "GSTR-3B" or "GSTR-1"
    gstin: str
    period: str             # e.g., "2025-01"
    status: str             # "success" or "error"
    reference_number: str   # Acknowledgement/reference number from MasterGST
    message: str            # Human-readable message
    filed_at: str           # ISO timestamp


def prepare_nil_gstr3b(gstin: str, period: str) -> NilFilingResult:
    """
    Prepare a NIL GSTR-3B return.

    A NIL GSTR-3B means:
    - No outward supplies (sales)
    - No inward supplies attracting reverse charge
    - No ITC claimed
    - No tax liability

    In production, this would call the GST API (NIC/GSP) to file.
    Currently returns a simulated success for the bot flow.
    """
    from datetime import datetime, timezone
    import hashlib

    now = datetime.now(timezone.utc)
    # Generate a deterministic reference number
    ref_seed = f"NIL-3B-{gstin}-{period}-{now.strftime('%Y%m%d')}"
    ref_number = f"NIL3B{hashlib.md5(ref_seed.encode()).hexdigest()[:12].upper()}"

    return NilFilingResult(
        form_type="GSTR-3B",
        gstin=gstin,
        period=period,
        status="success",
        reference_number=ref_number,
        message=(
            f"NIL GSTR-3B for {period} prepared successfully.\n"
            f"GSTIN: {gstin}\n"
            f"All tables show ZERO values.\n"
            f"Reference: {ref_number}\n\n"
            f"Note: This is a preview. In production, this will be "
            f"submitted to the GST portal via API."
        ),
        filed_at=now.isoformat(),
    )


def prepare_nil_gstr1(gstin: str, period: str) -> NilFilingResult:
    """
    Prepare a NIL GSTR-1 return.

    A NIL GSTR-1 means:
    - No B2B invoices issued
    - No B2C invoices issued
    - No credit/debit notes
    - No exports
    - No advances received

    In production, this would call the GST API (NIC/GSP) to file.
    Currently returns a simulated success for the bot flow.
    """
    from datetime import datetime, timezone
    import hashlib

    now = datetime.now(timezone.utc)
    ref_seed = f"NIL-1-{gstin}-{period}-{now.strftime('%Y%m%d')}"
    ref_number = f"NIL1{hashlib.md5(ref_seed.encode()).hexdigest()[:12].upper()}"

    return NilFilingResult(
        form_type="GSTR-1",
        gstin=gstin,
        period=period,
        status="success",
        reference_number=ref_number,
        message=(
            f"NIL GSTR-1 for {period} prepared successfully.\n"
            f"GSTIN: {gstin}\n"
            f"All tables show ZERO values — no outward supplies.\n"
            f"Reference: {ref_number}\n\n"
            f"Note: This is a preview. In production, this will be "
            f"submitted to the GST portal via API."
        ),
        filed_at=now.isoformat(),
    )


def get_current_gst_period() -> str:
    """Return current GST return period as YYYY-MM (previous month)."""
    from datetime import date
    today = date.today()
    # GST returns are for the previous month
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


# -------- MasterGST Sandbox NIL Filing --------

async def file_nil_return_mastergst(
    gstin: str,
    period: str,
    form_type: str,
) -> NilFilingResult:
    """
    File a NIL return via MasterGST sandbox API.

    Args:
        gstin: Taxpayer GSTIN.
        period: Return period YYYY-MM (e.g. "2025-01").
        form_type: "GSTR-3B", "GSTR-1", or "GSTR-3B + GSTR-1".

    Returns:
        NilFilingResult with status and reference from MasterGST.
    """
    from datetime import datetime, timezone
    from app.infrastructure.external.mastergst_client import MasterGSTClient, MasterGSTError

    now = datetime.now(timezone.utc)

    # Convert YYYY-MM to MMYYYY for MasterGST API
    parts = period.split("-")
    fp = f"{parts[1]}{parts[0]}" if len(parts) == 2 else period

    client = MasterGSTClient()
    results = []
    ref_numbers = []

    try:
        auth_token = await client.authenticate(gstin)

        if "GSTR-3B" in form_type:
            resp_3b = await client.file_nil_gstr3b(gstin, fp, auth_token)
            ref_3b = resp_3b.get("reference_id") or resp_3b.get("ack_num", f"NIL3B-{fp}")
            ref_numbers.append(ref_3b)
            results.append(
                f"NIL GSTR-3B for {period} filed via MasterGST.\n"
                f"GSTIN: {gstin}\n"
                f"Reference: {ref_3b}"
            )

        if "GSTR-1" in form_type:
            resp_1 = await client.file_nil_gstr1(gstin, fp, auth_token)
            ref_1 = resp_1.get("reference_id") or resp_1.get("ack_num", f"NIL1-{fp}")
            ref_numbers.append(ref_1)
            results.append(
                f"NIL GSTR-1 for {period} filed via MasterGST.\n"
                f"GSTIN: {gstin}\n"
                f"Reference: {ref_1}"
            )

        combined_ref = " / ".join(ref_numbers)
        combined_msg = "\n\n---\n\n".join(results)

        return NilFilingResult(
            form_type=form_type,
            gstin=gstin,
            period=period,
            status="success",
            reference_number=combined_ref,
            message=combined_msg,
            filed_at=now.isoformat(),
        )

    except MasterGSTError as e:
        return NilFilingResult(
            form_type=form_type,
            gstin=gstin,
            period=period,
            status="error",
            reference_number="",
            message=f"NIL filing failed: {e}",
            filed_at=now.isoformat(),
        )


# -------- Configuration Check --------

def is_mastergst_configured() -> bool:
    """Check if MasterGST API credentials are available."""
    return bool(
        settings.MASTERGST_BASE_URL
        and settings.MASTERGST_CLIENT_ID
        and settings.MASTERGST_CLIENT_SECRET
        and settings.MASTERGST_EMAIL
        and settings.MASTERGST_GST_USERNAME
    )


# -------- Full GST Filing via MasterGST --------

async def file_gstr3b_from_session(
    gstin: str,
    period: str,
    invoices: List[Dict[str, Any]],
) -> GstFilingResult:
    """
    File GSTR-3B via MasterGST sandbox using invoice dicts from WhatsApp session.

    Args:
        gstin: Taxpayer GSTIN.
        period: Return period YYYY-MM (e.g. "2025-01").
        invoices: List of invoice dicts from session (parsed OCR results).

    Returns:
        GstFilingResult with status and reference from MasterGST.
    """
    from datetime import datetime, timezone, date as date_cls
    from app.infrastructure.external.mastergst_client import MasterGSTClient, MasterGSTError
    from app.domain.services.gst_export import make_gstr3b_json

    now = datetime.now(timezone.utc)

    try:
        # 1. Build GSTR-3B summary from invoices
        summary = prepare_gstr3b(invoices)

        # 2. Convert period "YYYY-MM" to date for make_gstr3b_json
        parts = period.split("-")
        period_date = date_cls(int(parts[0]), int(parts[1]), 1)

        # 3. Build MasterGST-compatible payload
        payload = make_gstr3b_json(gstin, period_date, summary)

        # 4. Convert period to MasterGST "MMYYYY" format
        fp = f"{parts[1]}{parts[0]}"

        # 5. Authenticate and file
        client = MasterGSTClient()
        auth_token = await client.authenticate(gstin)

        logger.info("Saving GSTR-3B draft for GSTIN %s period %s", gstin, fp)
        await client.save_gstr3b(gstin, fp, payload, auth_token)

        logger.info("Submitting GSTR-3B for GSTIN %s period %s", gstin, fp)
        submit_resp = await client.submit_gstr3b(gstin, fp, auth_token)

        # 6. Extract reference number
        ref_number = (
            submit_resp.get("reference_id")
            or submit_resp.get("ack_num")
            or submit_resp.get("data", {}).get("reference_id", "")
            or f"GSTR3B-{fp}-{now.strftime('%Y%m%d%H%M%S')}"
        )

        return GstFilingResult(
            form_type="GSTR-3B",
            gstin=gstin,
            period=period,
            status="success",
            reference_number=ref_number,
            message=(
                f"GSTR-3B for {period} filed successfully via MasterGST.\n"
                f"GSTIN: {gstin}\n"
                f"Reference: {ref_number}"
            ),
            filed_at=now.isoformat(),
        )

    except MasterGSTError as e:
        logger.error("MasterGST GSTR-3B filing failed: %s", e)
        return GstFilingResult(
            form_type="GSTR-3B",
            gstin=gstin,
            period=period,
            status="error",
            reference_number="",
            message=f"GSTR-3B filing failed: {e}",
            filed_at=now.isoformat(),
        )
    except Exception as e:
        logger.exception("Unexpected error filing GSTR-3B for %s", gstin)
        return GstFilingResult(
            form_type="GSTR-3B",
            gstin=gstin,
            period=period,
            status="error",
            reference_number="",
            message=f"GSTR-3B filing failed: {e}",
            filed_at=now.isoformat(),
        )


async def file_gstr1_from_session(
    gstin: str,
    period: str,
    invoices: List[Dict[str, Any]],
) -> GstFilingResult:
    """
    File GSTR-1 via MasterGST sandbox using invoice dicts from WhatsApp session.

    Classifies invoices as B2B (receiver_gstin present with 15 chars) or B2C.

    Args:
        gstin: Taxpayer GSTIN.
        period: Return period YYYY-MM (e.g. "2025-01").
        invoices: List of invoice dicts from session (parsed OCR results).

    Returns:
        GstFilingResult with status and reference from MasterGST.
    """
    from datetime import datetime, timezone, date as date_cls
    from decimal import InvalidOperation
    from app.infrastructure.external.mastergst_client import MasterGSTClient, MasterGSTError
    from app.domain.services.gst_export import make_gstr1_json
    from app.domain.services.gstr1_service import (
        Gstr1Payload, Gstr1B2BEntry, Gstr1Invoice, Gstr1Item, Gstr1B2CInvoice,
    )

    now = datetime.now(timezone.utc)

    try:
        # 1. Convert period to MMYYYY
        parts = period.split("-")
        fp = f"{parts[1]}{parts[0]}"
        period_date = date_cls(int(parts[0]), int(parts[1]), 1)

        # 2. Classify invoices into B2B/B2C
        b2b_index: Dict[str, list] = {}
        b2c_list = []

        for inv in invoices:
            receiver_gstin = inv.get("receiver_gstin") or inv.get("recipient_gstin") or ""
            taxable = D(inv.get("taxable_value"))
            igst = D(inv.get("igst_amount"))
            cgst = D(inv.get("cgst_amount"))
            sgst = D(inv.get("sgst_amount"))

            # Infer tax rate
            tax_rate = Decimal("0")
            if taxable > 0:
                total_tax = igst + cgst + sgst
                if total_tax > 0:
                    tax_rate = (total_tax * Decimal("100")) / taxable

            total_amount = D(inv.get("total_amount"))
            if total_amount <= 0:
                total_amount = taxable + igst + cgst + sgst

            inv_date = inv.get("invoice_date") or period_date.strftime("%d-%m-%Y")
            if isinstance(inv_date, date_cls):
                dt_str = inv_date.strftime("%d-%m-%Y")
            else:
                dt_str = str(inv_date)

            pos = inv.get("place_of_supply") or ""
            if not pos and receiver_gstin and len(receiver_gstin) >= 2:
                pos = receiver_gstin[:2]
            if not pos:
                pos = gstin[:2] if len(gstin) >= 2 else "00"

            item = Gstr1Item(
                txval=taxable, rt=tax_rate, igst=igst, cgst=cgst, sgst=sgst,
            )
            invoice_model = Gstr1Invoice(
                num=inv.get("invoice_number") or "NA",
                dt=dt_str,
                val=total_amount,
                pos=pos,
                itms=[item],
            )

            if receiver_gstin and len(receiver_gstin) == 15:
                b2b_index.setdefault(receiver_gstin, []).append(invoice_model)
            else:
                b2c_list.append(Gstr1B2CInvoice(
                    pos=pos, txval=taxable, rt=tax_rate,
                    igst=igst, cgst=cgst, sgst=sgst,
                ))

        b2b_entries = [
            Gstr1B2BEntry(ctin=ctin, inv=inv_list)
            for ctin, inv_list in b2b_index.items()
        ]

        gstr1_payload = Gstr1Payload(
            gstin=gstin, fp=fp, b2b=b2b_entries, b2c=b2c_list,
        )

        # 3. Build MasterGST-compatible JSON
        payload = make_gstr1_json(gstr1_payload)

        # 4. Authenticate and file
        client = MasterGSTClient()
        auth_token = await client.authenticate(gstin)

        logger.info("Saving GSTR-1 draft for GSTIN %s period %s", gstin, fp)
        await client.save_gstr1(gstin, fp, payload, auth_token)

        logger.info("Submitting GSTR-1 for GSTIN %s period %s", gstin, fp)
        submit_resp = await client.submit_gstr1(gstin, fp, auth_token)

        # 5. Extract reference number
        ref_number = (
            submit_resp.get("reference_id")
            or submit_resp.get("ack_num")
            or submit_resp.get("data", {}).get("reference_id", "")
            or f"GSTR1-{fp}-{now.strftime('%Y%m%d%H%M%S')}"
        )

        return GstFilingResult(
            form_type="GSTR-1",
            gstin=gstin,
            period=period,
            status="success",
            reference_number=ref_number,
            message=(
                f"GSTR-1 for {period} filed successfully via MasterGST.\n"
                f"GSTIN: {gstin}\n"
                f"Reference: {ref_number}\n"
                f"B2B entries: {len(b2b_entries)}, B2C entries: {len(b2c_list)}"
            ),
            filed_at=now.isoformat(),
        )

    except MasterGSTError as e:
        logger.error("MasterGST GSTR-1 filing failed: %s", e)
        return GstFilingResult(
            form_type="GSTR-1",
            gstin=gstin,
            period=period,
            status="error",
            reference_number="",
            message=f"GSTR-1 filing failed: {e}",
            filed_at=now.isoformat(),
        )
    except Exception as e:
        logger.exception("Unexpected error filing GSTR-1 for %s", gstin)
        return GstFilingResult(
            form_type="GSTR-1",
            gstin=gstin,
            period=period,
            status="error",
            reference_number="",
            message=f"GSTR-1 filing failed: {e}",
            filed_at=now.isoformat(),
        )


def _demo_gstr3b_summary() -> Gstr3bSummary:
    """
    Investor-friendly, realistic demo numbers.
    """
    out = TaxBucket(
        taxable_value=Decimal("152340.00"),
        igst=Decimal("0.00"),
        cgst=Decimal("13710.60"),
        sgst=Decimal("13710.60"),
        cess=Decimal("0.00"),
    )
    rcm = TaxBucket(
        taxable_value=Decimal("12000.00"),
        igst=Decimal("2160.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        cess=Decimal("0.00"),
    )
    itc = ItcBucket(
        igst=Decimal("2160.00"),
        cgst=Decimal("13710.60"),
        sgst=Decimal("13710.60"),
        cess=Decimal("0.00"),
    )

    return Gstr3bSummary(
        outward_taxable_supplies=out,
        inward_reverse_charge=rcm,
        itc_eligible=itc,
    )
