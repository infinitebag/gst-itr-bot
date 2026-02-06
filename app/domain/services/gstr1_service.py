# app/domain/services/gstr1_service.py

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from app.infrastructure.db.repositories.invoice_repository import InvoiceRepository


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


# ---------- Dataclasses representing GSTR-1 structure ----------


@dataclass
class Gstr1Item:
    txval: Decimal
    rt: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal


@dataclass
class Gstr1Invoice:
    num: str  # invoice number
    dt: str  # DD-MM-YYYY
    val: Decimal  # invoice total value
    pos: str  # place of supply (2-digit code or state code)
    itms: list[Gstr1Item] = field(default_factory=list)


@dataclass
class Gstr1B2BEntry:
    ctin: str  # counterparty GSTIN
    inv: list[Gstr1Invoice] = field(default_factory=list)


@dataclass
class Gstr1B2CInvoice:
    pos: str
    txval: Decimal
    rt: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal


@dataclass
class Gstr1Payload:
    gstin: str
    fp: str  # filing period in MMYYYY format
    b2b: list[Gstr1B2BEntry] = field(default_factory=list)
    b2c: list[Gstr1B2CInvoice] = field(default_factory=list)


# ---------- Builder from invoices ----------


async def prepare_gstr1_payload(
    user_id,
    gstin: str,
    period_start: date,
    period_end: date,
    repo: InvoiceRepository,
) -> Gstr1Payload:
    """
    Build a lightweight GSTR-1 payload from saved outward invoices.

    Rules (simple v1):
    - If receiver_gstin present and looks like a GSTIN (len == 15) -> B2B.
    - Else -> B2C.
    - One Gstr1Item per invoice.
    """

    invoices = await repo.list_for_period(
        user_id=user_id,
        start=period_start,
        end=period_end,
    )

    # Filing period MMYYYY (e.g. 112025)
    fp = f"{period_start.month:02d}{period_start.year}"

    b2b_index: dict[str, list[Gstr1Invoice]] = {}
    b2c_list: list[Gstr1B2CInvoice] = []

    for inv in invoices:
        receiver_gstin = getattr(inv, "receiver_gstin", None) or getattr(
            inv, "recipient_gstin", None
        )

        taxable = _to_decimal(getattr(inv, "taxable_value", None))
        igst = _to_decimal(getattr(inv, "igst_amount", None))
        cgst = _to_decimal(getattr(inv, "cgst_amount", None))
        sgst = _to_decimal(getattr(inv, "sgst_amount", None))
        tax_rate = _to_decimal(getattr(inv, "tax_rate", None))

        # If rate is missing, try to infer from tax / taxable
        if tax_rate <= 0 and taxable > 0:
            total_tax = igst + cgst + sgst
            if total_tax > 0:
                tax_rate = (total_tax * Decimal("100")) / taxable

        total_amount = _to_decimal(getattr(inv, "total_amount", None))
        if total_amount <= 0:
            total_amount = taxable + igst + cgst + sgst

        inv_date = getattr(inv, "invoice_date", None) or period_start
        if isinstance(inv_date, date):
            dt_str = inv_date.strftime("%d-%m-%Y")
        else:
            dt_str = period_start.strftime("%d-%m-%Y")

        pos = getattr(inv, "place_of_supply", None) or ""
        pos = (pos or "").strip()
        if not pos and receiver_gstin and len(receiver_gstin) >= 2:
            pos = receiver_gstin[:2]
        if not pos:
            pos = "00"

        item = Gstr1Item(
            txval=taxable,
            rt=tax_rate,
            igst=igst,
            cgst=cgst,
            sgst=sgst,
        )

        invoice_model = Gstr1Invoice(
            num=getattr(inv, "invoice_number", None) or "NA",
            dt=dt_str,
            val=total_amount,
            pos=pos,
            itms=[item],
        )

        if receiver_gstin and len(receiver_gstin) == 15:
            # B2B
            ctin = receiver_gstin
            b2b_index.setdefault(ctin, []).append(invoice_model)
        else:
            # B2C
            b2c_list.append(
                Gstr1B2CInvoice(
                    pos=pos,
                    txval=taxable,
                    rt=tax_rate,
                    igst=igst,
                    cgst=cgst,
                    sgst=sgst,
                )
            )

    b2b_entries = [
        Gstr1B2BEntry(ctin=ctin, inv=inv_list) for ctin, inv_list in b2b_index.items()
    ]

    return Gstr1Payload(
        gstin=gstin,
        fp=fp,
        b2b=b2b_entries,
        b2c=b2c_list,
    )


# ---------- Local 'form' & WhatsApp text ----------


def prepare_gstr1_form(payload: Gstr1Payload) -> dict:
    """
    Build a small aggregate form from the payload for WhatsApp preview.
    """
    total_b2b_parties = len(payload.b2b)
    total_b2b_invoices = sum(len(entry.inv) for entry in payload.b2b)
    total_b2c_invoices = len(payload.b2c)

    total_txval = Decimal("0.00")
    for entry in payload.b2b:
        for inv in entry.inv:
            for item in inv.itms:
                total_txval += item.txval
    for inv in payload.b2c:
        total_txval += inv.txval

    return {
        "gstin": payload.gstin,
        "fp": payload.fp,
        "b2b_parties": total_b2b_parties,
        "b2b_invoices": total_b2b_invoices,
        "b2c_invoices": total_b2c_invoices,
        "total_txval": float(total_txval),
    }


def render_gstr1_text(form: dict, lang: str = "en") -> str:
    """
    WhatsApp-friendly text version of GSTR-1 form.
    """

    def fmt(v) -> str:
        try:
            return f"₹{float(v):,.2f}"
        except Exception:
            return "₹0.00"

    period = form.get("fp", "")
    if len(period) == 6:
        # MMYYYY -> YYYY-MM
        period_str = f"{period[2:]}-{period[0:2]}"
    else:
        period_str = period or "-"

    if lang == "en":
        lines: list[str] = [
            f"GSTR-1 preview for period {period_str}",
            f"GSTIN: {form.get('gstin', '-')}",
            "",
            f"B2B parties (GSTINs): {form.get('b2b_parties', 0)}",
            f"B2B invoices: {form.get('b2b_invoices', 0)}",
            f"B2C invoices: {form.get('b2c_invoices', 0)}",
            f"Total taxable value (approx): {fmt(form.get('total_txval', 0))}",
        ]
    else:
        lines = [
            f"अवधि {period_str} के लिए GSTR-1 पूर्वावलोकन",
            f"GSTIN: {form.get('gstin', '-')}",
            "",
            f"B2B पार्टियाँ (GSTIN): {form.get('b2b_parties', 0)}",
            f"B2B इनवॉइस: {form.get('b2b_invoices', 0)}",
            f"B2C इनवॉइस: {form.get('b2c_invoices', 0)}",
            f"कुल टैक्सेबल वैल्यू (लगभग): {fmt(form.get('total_txval', 0))}",
        ]

    return "\n".join(lines)
