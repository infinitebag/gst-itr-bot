# app/domain/services/gst_export.py
"""
Build GST return JSON payloads suitable for MasterGST API submission.

GSTR-3B: From Gstr3bSummary (TaxBucket/ItcBucket structure)
GSTR-1:  From Gstr1Payload (B2B/B2C entries from gstr1_service.py)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict

from app.domain.models.gst import Gstr3bSummary

# Backward-compat alias
Gstr3BSummary = Gstr3bSummary


def _d(val: Decimal | None) -> float:
    """Convert Decimal to float for JSON serialization."""
    if val is None:
        return 0.0
    return float(val)


def make_gstr3b_json(
    gstin: str,
    period: date,
    summary: Gstr3bSummary,
) -> Dict[str, Any]:
    """
    Build GSTR-3B JSON from a Gstr3bSummary.

    Args:
        gstin: Taxpayer's GSTIN.
        period: Filing period as a date (uses month/year).
        summary: Gstr3bSummary with outward_taxable_supplies,
                 inward_reverse_charge, itc_eligible.

    Returns:
        Dict matching MasterGST GSTR-3B API schema.
    """
    out = summary.outward_taxable_supplies
    rcm = summary.inward_reverse_charge
    itc = summary.itc_eligible

    # Filing period: MMYYYY (e.g. "012025")
    fp = f"{period.month:02d}{period.year}"

    return {
        "gstin": gstin,
        "fp": fp,
        "sup_details": {
            "osup_det": {
                "txval": _d(out.taxable_value),
                "igst": _d(out.igst),
                "cgst": _d(out.cgst),
                "sgst": _d(out.sgst),
                "cess": _d(out.cess),
            },
            "osup_zero": {
                "txval": 0, "igst": 0, "cgst": 0, "sgst": 0, "cess": 0,
            },
            "osup_nil_exmp": {
                "txval": _d(summary.outward_nil_exempt),
            },
            "osup_nongst": {
                "txval": _d(summary.outward_non_gst),
            },
            "isup_rev": {
                "txval": _d(rcm.taxable_value),
                "igst": _d(rcm.igst),
                "cgst": _d(rcm.cgst),
                "sgst": _d(rcm.sgst),
                "cess": _d(rcm.cess),
            },
        },
        "itc_elg": {
            "itc_avl": [
                {
                    "ty": "IMPG",
                    "igst": _d(itc.igst),
                    "cgst": _d(itc.cgst),
                    "sgst": _d(itc.sgst),
                    "cess": _d(itc.cess),
                },
            ],
            "itc_rev": [],
            "itc_net": {
                "igst": _d(itc.igst),
                "cgst": _d(itc.cgst),
                "sgst": _d(itc.sgst),
                "cess": _d(itc.cess),
            },
            "itc_inelg": [],
        },
        "inward_sup": {
            "isup_details": [
                {"ty": "GST", "inter": 0, "intra": 0},
                {"ty": "NONGST", "inter": 0, "intra": 0},
            ]
        },
        "intr_ltfee": {
            "intr_details": {"igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
        },
    }


def make_gstr1_json(payload) -> Dict[str, Any]:
    """
    Build GSTR-1 JSON from a Gstr1Payload dataclass.

    Args:
        payload: Gstr1Payload from gstr1_service.py containing
                 gstin, fp, b2b entries, and b2c entries.

    Returns:
        Dict matching MasterGST GSTR-1 API schema.
    """
    # Serialize B2B entries
    b2b_list = []
    for entry in payload.b2b:
        inv_list = []
        for inv in entry.inv:
            items = []
            for item in inv.itms:
                items.append({
                    "num": 1,
                    "itm_det": {
                        "txval": _d(item.txval),
                        "rt": _d(item.rt),
                        "iamt": _d(item.igst),
                        "camt": _d(item.cgst),
                        "samt": _d(item.sgst),
                        "csamt": 0,
                    },
                })
            inv_list.append({
                "inum": inv.num,
                "idt": inv.dt,
                "val": _d(inv.val),
                "pos": inv.pos,
                "rchrg": "N",
                "inv_typ": "R",
                "itms": items,
            })
        b2b_list.append({
            "ctin": entry.ctin,
            "inv": inv_list,
        })

    # Serialize B2C entries
    b2cs_list = []
    for b2c in payload.b2c:
        b2cs_list.append({
            "pos": b2c.pos,
            "typ": "OE",
            "txval": _d(b2c.txval),
            "rt": _d(b2c.rt),
            "iamt": _d(b2c.igst),
            "camt": _d(b2c.cgst),
            "samt": _d(b2c.sgst),
            "csamt": 0,
        })

    # Calculate grand total
    grand_total = 0.0
    for entry in payload.b2b:
        for inv in entry.inv:
            grand_total += _d(inv.val)
    for b2c in payload.b2c:
        grand_total += _d(b2c.txval)

    return {
        "gstin": payload.gstin,
        "fp": payload.fp,
        "gt": grand_total,
        "b2b": b2b_list,
        "b2cs": b2cs_list,
        "b2cl": [],
        "cdnr": [],
        "cdnur": [],
        "exp": [],
        "nil": {"inv": []},
        "hsn": {"data": []},
        "doc_issue": {"doc_det": []},
    }
