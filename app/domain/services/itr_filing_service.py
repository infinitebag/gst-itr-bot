# app/domain/services/itr_filing_service.py
"""
ITR e-filing service — submits computed ITR data to the ITR sandbox.

Wraps ItrSandboxClient to provide a clean interface for the WhatsApp bot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger("itr_filing_service")


@dataclass
class ItrFilingResult:
    """Result of an ITR e-filing submission."""
    form_type: str          # "ITR-1" or "ITR-4"
    pan: str
    assessment_year: str
    status: str             # "success" or "error"
    reference_number: str   # Acknowledgement/reference from sandbox
    message: str            # Human-readable message
    filed_at: str           # ISO timestamp


def is_itr_sandbox_configured() -> bool:
    """Check if ITR sandbox credentials are available."""
    from app.infrastructure.external.itr_client_sandbox import ItrSandboxClient
    return ItrSandboxClient.is_configured()


def _decimal_to_float(val) -> float:
    """Safely convert a Decimal or any numeric to float."""
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _build_itr1_payload(
    inp,  # ITR1Input
    result,  # ITRResult
    pan: str,
    assessment_year: str,
) -> dict:
    """Build ITR-1 submission payload from computed inputs and result."""
    # Use the recommended regime's breakdown
    breakdown = result.new_regime if result.recommended_regime == "new" else result.old_regime
    if not breakdown:
        breakdown = result.new_regime or result.old_regime

    return {
        "form_type": "ITR-1",
        "pan": pan,
        "assessment_year": assessment_year,
        "regime": result.recommended_regime or "new",
        "income": {
            "salary": _decimal_to_float(inp.salary_income),
            "standard_deduction": _decimal_to_float(inp.standard_deduction),
            "house_property": _decimal_to_float(inp.house_property_income),
            "other_income": _decimal_to_float(inp.other_income),
        },
        "deductions": {
            "section_80c": _decimal_to_float(inp.section_80c),
            "section_80d": _decimal_to_float(inp.section_80d),
            "section_80tta": _decimal_to_float(inp.section_80tta),
        },
        "tax_computation": {
            "gross_total_income": _decimal_to_float(breakdown.gross_total_income) if breakdown else 0.0,
            "total_deductions": _decimal_to_float(breakdown.total_deductions) if breakdown else 0.0,
            "taxable_income": _decimal_to_float(breakdown.taxable_income) if breakdown else 0.0,
            "tax_on_income": _decimal_to_float(breakdown.tax_on_income) if breakdown else 0.0,
            "surcharge": _decimal_to_float(breakdown.surcharge) if breakdown else 0.0,
            "health_cess": _decimal_to_float(breakdown.health_cess) if breakdown else 0.0,
            "total_tax_liability": _decimal_to_float(breakdown.total_tax_liability) if breakdown else 0.0,
            "tds_total": _decimal_to_float(inp.tds_total),
            "advance_tax": _decimal_to_float(inp.advance_tax),
        },
    }


def _build_itr4_payload(
    inp,  # ITR4Input
    result,  # ITRResult
    pan: str,
    assessment_year: str,
) -> dict:
    """Build ITR-4 submission payload from computed inputs and result."""
    breakdown = result.new_regime if result.recommended_regime == "new" else result.old_regime
    if not breakdown:
        breakdown = result.new_regime or result.old_regime

    return {
        "form_type": "ITR-4",
        "pan": pan,
        "assessment_year": assessment_year,
        "regime": result.recommended_regime or "new",
        "business_income": {
            "gross_turnover": _decimal_to_float(inp.gross_turnover),
            "presumptive_rate": _decimal_to_float(inp.presumptive_rate),
            "gross_receipts": _decimal_to_float(inp.gross_receipts),
            "professional_rate": _decimal_to_float(inp.professional_rate),
        },
        "deductions": {
            "section_80c": _decimal_to_float(inp.section_80c),
        },
        "tax_computation": {
            "gross_total_income": _decimal_to_float(breakdown.gross_total_income) if breakdown else 0.0,
            "total_deductions": _decimal_to_float(breakdown.total_deductions) if breakdown else 0.0,
            "taxable_income": _decimal_to_float(breakdown.taxable_income) if breakdown else 0.0,
            "tax_on_income": _decimal_to_float(breakdown.tax_on_income) if breakdown else 0.0,
            "surcharge": _decimal_to_float(breakdown.surcharge) if breakdown else 0.0,
            "health_cess": _decimal_to_float(breakdown.health_cess) if breakdown else 0.0,
            "total_tax_liability": _decimal_to_float(breakdown.total_tax_liability) if breakdown else 0.0,
            "tds_total": _decimal_to_float(inp.tds_total),
        },
    }


async def submit_itr_to_sandbox(
    form_type: str,
    inp: Any,       # ITR1Input or ITR4Input
    result: Any,    # ITRResult
    pan: str = "",
    assessment_year: str = "2025-26",
) -> ItrFilingResult:
    """
    Submit an ITR computation to the ITR sandbox for e-filing.

    Args:
        form_type: "ITR-1" or "ITR-4"
        inp: The ITR input (ITR1Input or ITR4Input)
        result: The computed ITRResult
        pan: PAN number (taken from inp if empty)
        assessment_year: Assessment year (taken from inp if empty)

    Returns:
        ItrFilingResult with status and reference.
    """
    from app.infrastructure.external.itr_client_sandbox import (
        ItrSandboxClient,
        ItrSandboxError,
    )

    now = datetime.now(timezone.utc)

    # Resolve PAN and AY from input if not provided
    pan = pan or getattr(inp, "pan", "") or "UNKNOWN"
    assessment_year = assessment_year or getattr(inp, "assessment_year", "2025-26")

    try:
        client = ItrSandboxClient()

        if form_type == "ITR-1":
            payload = _build_itr1_payload(inp, result, pan, assessment_year)
            logger.info("Submitting ITR-1 to sandbox for PAN %s AY %s", pan, assessment_year)
            resp = await client.submit_itr1(payload)
        else:
            payload = _build_itr4_payload(inp, result, pan, assessment_year)
            logger.info("Submitting ITR-4 to sandbox for PAN %s AY %s", pan, assessment_year)
            resp = await client.submit_itr4(payload)

        # Extract reference from response
        ref_number = (
            resp.get("reference_id")
            or resp.get("ack_num")
            or resp.get("acknowledgement_number")
            or resp.get("data", {}).get("reference_id", "")
            or f"{form_type.replace('-', '')}-{now.strftime('%Y%m%d%H%M%S')}"
        )

        return ItrFilingResult(
            form_type=form_type,
            pan=pan,
            assessment_year=assessment_year,
            status="success",
            reference_number=ref_number,
            message=(
                f"{form_type} submitted successfully!\n"
                f"PAN: {pan}\n"
                f"Assessment Year: {assessment_year}\n"
                f"Reference: {ref_number}"
            ),
            filed_at=now.isoformat(),
        )

    except ItrSandboxError as e:
        logger.error("ITR sandbox submission failed: %s", e)
        return ItrFilingResult(
            form_type=form_type,
            pan=pan,
            assessment_year=assessment_year,
            status="error",
            reference_number="",
            message=f"{form_type} submission failed: {e}",
            filed_at=now.isoformat(),
        )
    except RuntimeError as e:
        # ItrSandboxClient.__init__ raises RuntimeError if not configured
        logger.error("ITR sandbox not configured: %s", e)
        return ItrFilingResult(
            form_type=form_type,
            pan=pan,
            assessment_year=assessment_year,
            status="error",
            reference_number="",
            message=f"{form_type} submission failed: ITR sandbox not configured",
            filed_at=now.isoformat(),
        )
    except Exception as e:
        logger.exception("Unexpected error submitting %s", form_type)
        return ItrFilingResult(
            form_type=form_type,
            pan=pan,
            assessment_year=assessment_year,
            status="error",
            reference_number="",
            message=f"{form_type} submission failed: {e}",
            filed_at=now.isoformat(),
        )
