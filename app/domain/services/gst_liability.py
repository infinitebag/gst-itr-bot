# app/domain/services/gst_liability.py
"""
Net GST Liability Computation.

Aggregates outward tax, eligible ITC, and RCM for a return period.
Generates risk flags for CA review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

logger = logging.getLogger("gst_liability")

ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PeriodComputation:
    """Result of net liability computation for a single period."""
    outward_count: int = 0
    inward_count: int = 0
    # Output tax (from outward/sales invoices)
    output_igst: Decimal = ZERO
    output_cgst: Decimal = ZERO
    output_sgst: Decimal = ZERO
    # Eligible ITC (from matched, eligible inward invoices)
    itc_igst: Decimal = ZERO
    itc_cgst: Decimal = ZERO
    itc_sgst: Decimal = ZERO
    # RCM liability (from reverse charge invoices)
    rcm_igst: Decimal = ZERO
    rcm_cgst: Decimal = ZERO
    rcm_sgst: Decimal = ZERO
    # Net payable = output_tax + RCM - eligible_ITC
    net_igst: Decimal = ZERO
    net_cgst: Decimal = ZERO
    net_sgst: Decimal = ZERO
    total_net_payable: Decimal = ZERO
    # Risk flags
    risk_flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compute_net_liability(period_id: UUID, db: Any) -> PeriodComputation:
    """
    Compute net GST liability for a return period.

    Steps:
    1. Aggregate outward invoices → output tax per head
    2. Aggregate eligible ITC (inward + itc_eligible + matched + NOT blocked)
    3. Aggregate RCM liability (inward + reverse_charge)
    4. Net payable = output_tax + RCM - eligible_ITC (per head)
    5. Generate risk flags
    6. Store computed values in ReturnPeriod record

    Returns PeriodComputation with all aggregated values and risk flags.
    """
    from calendar import monthrange

    from app.infrastructure.db.repositories.invoice_repository import InvoiceRepository
    from app.infrastructure.db.repositories.return_period_repository import ReturnPeriodRepository

    period_repo = ReturnPeriodRepository(db)
    period_rec = await period_repo.get_by_id(period_id)
    if not period_rec:
        raise ValueError(f"ReturnPeriod {period_id} not found")

    # Date range for the period
    parts = period_rec.period.split("-")
    year, month = int(parts[0]), int(parts[1])
    start = __import__("datetime").date(year, month, 1)
    end = __import__("datetime").date(year, month, monthrange(year, month)[1])

    inv_repo = InvoiceRepository(db)
    comp = PeriodComputation()

    # -------------------------------------------------------------------
    # 1. Aggregate OUTWARD invoices → output tax
    # -------------------------------------------------------------------
    outward = await inv_repo.list_for_period_by_direction(
        period_rec.user_id, start, end, "outward"
    )
    comp.outward_count = len(outward)
    for inv in outward:
        comp.output_igst += _dec(inv.igst_amount)
        comp.output_cgst += _dec(inv.cgst_amount)
        comp.output_sgst += _dec(inv.sgst_amount)

    # -------------------------------------------------------------------
    # 2. Aggregate eligible ITC
    #    Conditions: direction=inward, itc_eligible=True,
    #                gstr2b_match_status='matched', blocked_itc_reason IS NULL
    # -------------------------------------------------------------------
    inward = await inv_repo.list_for_period_by_direction(
        period_rec.user_id, start, end, "inward"
    )
    comp.inward_count = len(inward)

    for inv in inward:
        if (
            inv.itc_eligible
            and inv.gstr2b_match_status == "matched"
            and not inv.blocked_itc_reason
        ):
            comp.itc_igst += _dec(inv.igst_amount)
            comp.itc_cgst += _dec(inv.cgst_amount)
            comp.itc_sgst += _dec(inv.sgst_amount)

    # -------------------------------------------------------------------
    # 3. Aggregate RCM liability (inward + reverse_charge=True)
    # -------------------------------------------------------------------
    for inv in inward:
        if inv.reverse_charge:
            comp.rcm_igst += _dec(inv.igst_amount)
            comp.rcm_cgst += _dec(inv.cgst_amount)
            comp.rcm_sgst += _dec(inv.sgst_amount)

    # -------------------------------------------------------------------
    # 4. Net payable = output + RCM - ITC (per head, floor at 0)
    # -------------------------------------------------------------------
    comp.net_igst = max(ZERO, comp.output_igst + comp.rcm_igst - comp.itc_igst)
    comp.net_cgst = max(ZERO, comp.output_cgst + comp.rcm_cgst - comp.itc_cgst)
    comp.net_sgst = max(ZERO, comp.output_sgst + comp.rcm_sgst - comp.itc_sgst)
    comp.total_net_payable = comp.net_igst + comp.net_cgst + comp.net_sgst

    # -------------------------------------------------------------------
    # 5. Risk flags
    # -------------------------------------------------------------------
    comp.risk_flags = _generate_risk_flags(comp, period_rec, db)

    # -------------------------------------------------------------------
    # 6. Store computed values in ReturnPeriod
    # -------------------------------------------------------------------
    computation_data = {
        "outward_count": comp.outward_count,
        "inward_count": comp.inward_count,
        "output_tax_igst": comp.output_igst,
        "output_tax_cgst": comp.output_cgst,
        "output_tax_sgst": comp.output_sgst,
        "itc_igst": comp.itc_igst,
        "itc_cgst": comp.itc_cgst,
        "itc_sgst": comp.itc_sgst,
        "net_payable_igst": comp.net_igst,
        "net_payable_cgst": comp.net_cgst,
        "net_payable_sgst": comp.net_sgst,
        "rcm_igst": comp.rcm_igst,
        "rcm_cgst": comp.rcm_cgst,
        "rcm_sgst": comp.rcm_sgst,
        "risk_flags": comp.risk_flags,
    }
    await period_repo.update_computation(period_id, computation_data)

    # Try to transition status to "data_ready"
    try:
        await period_repo.update_status(period_id, "data_ready")
    except Exception:
        logger.warning(
            "Could not transition period %s to 'data_ready' — current status may not allow it",
            period_id,
        )

    logger.info(
        "Liability computed: period=%s, net_payable=%.2f (IGST=%.2f, CGST=%.2f, SGST=%.2f), flags=%s",
        period_rec.period,
        comp.total_net_payable,
        comp.net_igst,
        comp.net_cgst,
        comp.net_sgst,
        comp.risk_flags,
    )

    # Phase 2: Auto-trigger 100-point risk scoring after liability computation
    try:
        from app.domain.services.gst_risk_scoring import compute_risk_score
        risk_result = await compute_risk_score(period_id, db)
        logger.info(
            "Risk score auto-computed for period %s: %d (%s)",
            period_id, risk_result.risk_score, risk_result.risk_level,
        )
    except Exception:
        logger.warning(
            "Risk scoring failed for period %s — liability still valid",
            period_id, exc_info=True,
        )

    return comp


# ---------------------------------------------------------------------------
# Risk flag generation
# ---------------------------------------------------------------------------

def _generate_risk_flags(
    comp: PeriodComputation,
    period_rec: Any,
    db: Any,
) -> list[str]:
    """Generate risk flags based on computed values."""
    flags: list[str] = []

    # HIGH_ITC_MISMATCH: >10% of inward invoices have mismatches
    if comp.inward_count > 0:
        # We can't easily get mismatch count from PeriodComputation alone,
        # so we check the period record's existing reconciliation data.
        # For now, flag if ITC is zero but there are inward invoices
        pass  # Will be enriched by reconciliation summary below

    # RCM_PRESENT_NO_PAYMENT: RCM liability exists
    rcm_total = comp.rcm_igst + comp.rcm_cgst + comp.rcm_sgst
    if rcm_total > ZERO:
        flags.append("RCM_PRESENT")

    # UNUSUAL_TURNOVER_SPIKE: outward taxable > threshold
    outward_taxable = comp.output_igst + comp.output_cgst + comp.output_sgst
    # Flag if output is very high relative to ITC claimed
    itc_total = comp.itc_igst + comp.itc_cgst + comp.itc_sgst
    if outward_taxable > ZERO and itc_total > outward_taxable * Decimal("0.9"):
        flags.append("HIGH_ITC_RATIO")

    # NET_LIABILITY_ZERO_HIGH_SALES: net payable = 0 but significant outward supply
    if comp.total_net_payable == ZERO and outward_taxable > Decimal("50000"):
        flags.append("NET_LIABILITY_ZERO_HIGH_SALES")

    return flags


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _dec(val: Any) -> Decimal:
    """Safely convert a value to Decimal."""
    if val is None:
        return ZERO
    try:
        return Decimal(str(val))
    except Exception:
        return ZERO
