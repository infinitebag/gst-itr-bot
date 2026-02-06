# app/domain/services/gst_service.py

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

try:
    # If you already have proper domain models, we will prefer them.
    # Keep this import if your project has app/domain/models/gst.py
    from app.domain.models.gst import Gstr3bSummary as _Gstr3bSummary  # type: ignore
except Exception:
    _Gstr3bSummary = None


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


# -------- Minimal models (fallback) --------
# These are ONLY used if your app.domain.models.gst.Gstr3bSummary is not available.

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore
    Field = lambda default=None, **kwargs: default  # type: ignore


class TaxBucket(BaseModel):
    taxable_value: Decimal = Field(default=Decimal("0"))
    igst: Decimal = Field(default=Decimal("0"))
    cgst: Decimal = Field(default=Decimal("0"))
    sgst: Decimal = Field(default=Decimal("0"))
    cess: Decimal = Field(default=Decimal("0"))


class ItcBucket(BaseModel):
    igst: Decimal = Field(default=Decimal("0"))
    cgst: Decimal = Field(default=Decimal("0"))
    sgst: Decimal = Field(default=Decimal("0"))
    cess: Decimal = Field(default=Decimal("0"))


class Gstr3bSummaryFallback(BaseModel):
    outward_taxable_supplies: TaxBucket = Field(default_factory=TaxBucket)
    inward_reverse_charge: TaxBucket = Field(default_factory=TaxBucket)
    itc_eligible: ItcBucket = Field(default_factory=ItcBucket)

    # Optional extra fields you might want later
    outward_nil_exempt: Decimal = Field(default=Decimal("0"))
    outward_non_gst: Decimal = Field(default=Decimal("0"))


# Pick the real model if it exists, otherwise fallback
Gstr3bSummary = _Gstr3bSummary or Gstr3bSummaryFallback

# Backward-compat alias (fixes your earlier ImportError)
Gstr3BSummary = Gstr3bSummary


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

    out = TaxBucket(taxable_value=Decimal("0"), igst=Decimal("0"), cgst=Decimal("0"), sgst=Decimal("0"), cess=Decimal("0"))
    rcm = TaxBucket(taxable_value=Decimal("0"), igst=Decimal("0"), cgst=Decimal("0"), sgst=Decimal("0"), cess=Decimal("0"))
    itc = ItcBucket(igst=Decimal("0"), cgst=Decimal("0"), sgst=Decimal("0"), cess=Decimal("0"))

    for inv in invoices:
        taxable = D(inv.get("taxable_value"))
        igst = D(inv.get("igst_amount"))
        cgst = D(inv.get("cgst_amount"))
        sgst = D(inv.get("sgst_amount"))
        cess = D(inv.get("cess_amount"))

        is_rcm = bool(inv.get("reverse_charge", False))
        is_itc = bool(inv.get("itc_eligible", True))  # default True

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

    # Create whichever summary model is active
    if _Gstr3bSummary:
        # If your real domain model exists, it likely accepts these fields.
        return Gstr3bSummary(
            outward_taxable_supplies=out,
            inward_reverse_charge=rcm,
            itc_eligible=itc,
        )

    return Gstr3bSummaryFallback(
        outward_taxable_supplies=out,
        inward_reverse_charge=rcm,
        itc_eligible=itc,
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

    if _Gstr3bSummary:
        return Gstr3bSummary(
            outward_taxable_supplies=out,
            inward_reverse_charge=rcm,
            itc_eligible=itc,
        )

    return Gstr3bSummaryFallback(
        outward_taxable_supplies=out,
        inward_reverse_charge=rcm,
        itc_eligible=itc,
    )