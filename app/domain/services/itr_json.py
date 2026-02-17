# app/domain/services/itr_json.py
"""
Generate structured ITR-1 and ITR-4 JSON data from computed tax results.

These JSON structures mirror the official ITR form layouts and can be used
for PDF generation, API responses, or downstream integrations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.services.itr_service import (
    ITR1Input,
    ITR4Input,
    ITRResult,
    TaxBreakdown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _breakdown_to_dict(b: TaxBreakdown) -> dict:
    """Convert a TaxBreakdown dataclass to a plain dict with camelCase keys."""
    return {
        "regime": b.regime,
        "grossTotalIncome": float(b.gross_total_income),
        "totalDeductions": float(b.total_deductions),
        "taxableIncome": float(b.taxable_income),
        "taxOnIncome": float(b.tax_on_income),
        "rebate87A": float(b.rebate_87a),
        "surcharge": float(b.surcharge),
        "healthCess": float(b.health_cess),
        "totalTaxLiability": float(b.total_tax_liability),
        "taxesPaid": float(b.taxes_paid),
        "taxPayable": float(b.tax_payable),
        "slabDetails": b.slab_details,
    }


# ---------------------------------------------------------------------------
# ITR-1 JSON
# ---------------------------------------------------------------------------

def generate_itr1_json(inp: ITR1Input, result: ITRResult) -> dict:
    """
    Generate a structured JSON dict for ITR-1 (Sahaj).

    Parameters
    ----------
    inp : ITR1Input
        The original inputs used for computation.
    result : ITRResult
        The computed result containing old/new regime breakdowns.

    Returns
    -------
    dict
        A structured dictionary matching ITR-1 form layout.
    """
    rec = (
        result.old_regime
        if result.recommended_regime == "old"
        else result.new_regime
    )

    return {
        "formType": "ITR-1",
        "assessmentYear": inp.assessment_year,
        "personalInfo": {
            "pan": inp.pan,
            "name": inp.name,
            "assessmentYear": inp.assessment_year,
        },
        "incomeDetails": {
            "grossSalary": float(inp.salary_income),
            "standardDeduction": float(inp.standard_deduction),
            "netSalary": float(
                max(inp.salary_income - inp.standard_deduction, Decimal("0"))
            ),
            "housePropertyIncome": float(inp.house_property_income),
            "otherIncome": float(inp.other_income),
            "grossTotalIncome": float(rec.gross_total_income),
        },
        "deductions": {
            "section80C": float(inp.section_80c),
            "section80D": float(inp.section_80d),
            "section80E": float(inp.section_80e),
            "section80G": float(inp.section_80g),
            "section80TTA": float(inp.section_80tta),
            "section80CCD1B": float(inp.section_80ccd_1b),
            "otherDeductions": float(inp.other_deductions),
            "totalDeductions": float(rec.total_deductions),
        },
        "taxComputation": {
            "recommendedRegime": result.recommended_regime,
            "savings": float(result.savings),
            "oldRegime": _breakdown_to_dict(result.old_regime),
            "newRegime": _breakdown_to_dict(result.new_regime),
        },
        "taxPayments": {
            "tdsTotal": float(inp.tds_total),
            "advanceTax": float(inp.advance_tax),
            "selfAssessmentTax": float(inp.self_assessment_tax),
            "totalPaid": float(
                inp.tds_total + inp.advance_tax + inp.self_assessment_tax
            ),
        },
        "verification": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "computedBy": "GST-ITR Bot",
            "disclaimer": (
                "This is a computer-generated computation. "
                "Please verify with a CA."
            ),
        },
    }


# ---------------------------------------------------------------------------
# ITR-4 JSON
# ---------------------------------------------------------------------------

def generate_itr4_json(inp: ITR4Input, result: ITRResult) -> dict:
    """
    Generate a structured JSON dict for ITR-4 (Sugam).

    Parameters
    ----------
    inp : ITR4Input
        The original inputs used for computation.
    result : ITRResult
        The computed result containing old/new regime breakdowns.

    Returns
    -------
    dict
        A structured dictionary matching ITR-4 form layout.
    """
    rec = (
        result.old_regime
        if result.recommended_regime == "old"
        else result.new_regime
    )

    deemed_profit = inp.gross_turnover * inp.presumptive_rate / 100
    professional_income = inp.gross_receipts * inp.professional_rate / 100

    return {
        "formType": "ITR-4",
        "assessmentYear": inp.assessment_year,
        "personalInfo": {
            "pan": inp.pan,
            "name": inp.name,
            "assessmentYear": inp.assessment_year,
        },
        "businessIncome": {
            "grossTurnover": float(inp.gross_turnover),
            "presumptiveRate": float(inp.presumptive_rate),
            "deemedProfit": float(deemed_profit),
            "grossReceipts": float(inp.gross_receipts),
            "professionalRate": float(inp.professional_rate),
            "professionalIncome": float(professional_income),
        },
        "otherIncome": {
            "salary": float(inp.salary_income),
            "housePropertyIncome": float(inp.house_property_income),
            "otherIncome": float(inp.other_income),
        },
        "deductions": {
            "section80C": float(inp.section_80c),
            "section80D": float(inp.section_80d),
            "otherDeductions": float(inp.other_deductions),
            "totalDeductions": float(rec.total_deductions),
        },
        "taxComputation": {
            "recommendedRegime": result.recommended_regime,
            "savings": float(result.savings),
            "oldRegime": _breakdown_to_dict(result.old_regime),
            "newRegime": _breakdown_to_dict(result.new_regime),
        },
        "taxPayments": {
            "tdsTotal": float(inp.tds_total),
            "advanceTax": float(inp.advance_tax),
            "totalPaid": float(inp.tds_total + inp.advance_tax),
        },
        "verification": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "computedBy": "GST-ITR Bot",
            "disclaimer": (
                "This is a computer-generated computation. "
                "Please verify with a CA."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def itr_json_to_string(data: dict) -> str:
    """Serialise an ITR JSON dict to a pretty-printed JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# e-Filing Portal Compatible JSON (incometax.gov.in schema)
# ---------------------------------------------------------------------------

def _fl(val: Decimal | float) -> float:
    """Safe float conversion."""
    return round(float(val), 2)


def generate_itr1_efiling_json(
    inp: ITR1Input,
    result: ITRResult,
    personal_info: dict | None = None,
) -> dict:
    """
    Generate ITR-1 JSON compatible with the incometax.gov.in e-filing portal.

    The user can download this JSON and upload it to the portal for filing.

    Parameters
    ----------
    inp : ITR1Input
    result : ITRResult
    personal_info : dict, optional
        Extra personal details (firstName, middleName, surName, dob, aadhaar, address).
    """
    pi = personal_info or {}
    rec = result.old_regime if result.recommended_regime == "old" else result.new_regime
    opt_out_new = "Y" if result.recommended_regime == "old" else "N"

    net_salary = max(inp.salary_income - inp.standard_deduction, Decimal("0"))
    gti = rec.gross_total_income
    total_deductions = rec.total_deductions
    taxable_income = rec.taxable_income
    total_paid = inp.tds_total + inp.advance_tax + inp.self_assessment_tax

    return {
        "Form_ITR1": {
            "FormName": "ITR-1",
            "Description": "For Individuals having Income from Salaries, One House Property, Other Sources (Interest etc.)",
            "AssessmentYear": inp.assessment_year.replace("-", ""),  # "202526"
            "SchemaVer": "Ver1.0",
            "FormVer": "Ver1.0",
        },
        "PersonalInfo": {
            "AssesseeName": {
                "FirstName": pi.get("firstName", inp.name or ""),
                "MiddleName": pi.get("middleName", ""),
                "SurNameOrOrgName": pi.get("surName", ""),
            },
            "PAN": inp.pan,
            "DOB": pi.get("dob", ""),
            "AadhaarCardNo": pi.get("aadhaar", ""),
            "Address": pi.get("address", {}),
        },
        "FilingStatus": {
            "ReturnFileSec": 11,  # Original return
            "OptOutNewTaxRegime": opt_out_new,
        },
        "ITR1_IncomeDeductions": {
            "GrossSalary": _fl(inp.salary_income),
            "Salary": _fl(net_salary),
            "IncomeFromHP": _fl(inp.house_property_income),
            "IncomeOthSrc": _fl(inp.other_income),
            "GrossTotIncome": _fl(gti),
            "DeductUndChapVIA": {
                "Section80C": _fl(inp.section_80c),
                "Section80D": _fl(inp.section_80d),
                "Section80E": _fl(inp.section_80e),
                "Section80G": _fl(inp.section_80g),
                "Section80TTA": _fl(inp.section_80tta),
                "Section80CCD1B": _fl(inp.section_80ccd_1b),
                "OtherDeductions": _fl(inp.other_deductions),
                "TotalChapVIADeductions": _fl(total_deductions),
            },
            "TotalIncome": _fl(taxable_income),
        },
        "ITR1_TaxComputation": {
            "TotalTaxPayable": _fl(rec.tax_on_income),
            "Rebate87A": _fl(rec.rebate_87a),
            "TaxPayableOnTI": _fl(rec.tax_on_income - rec.rebate_87a),
            "SurchargeOnAboveCrore": _fl(rec.surcharge),
            "EducationCess": _fl(rec.health_cess),
            "GrossTaxLiability": _fl(rec.total_tax_liability),
            "TotalTaxesPaid": {
                "TDS": _fl(inp.tds_total),
                "TCS": 0.0,
                "AdvanceTax": _fl(inp.advance_tax),
                "SelfAssessmentTax": _fl(inp.self_assessment_tax),
                "TotalPaid": _fl(total_paid),
            },
            "BalTaxPayable": _fl(rec.tax_payable),
        },
        "TDSonSalaries": [],
        "Verification": {
            "Declaration": (
                "I declare that the information given in this return is correct "
                "and complete."
            ),
            "GeneratedAt": datetime.now(timezone.utc).isoformat(),
            "GeneratedBy": "GST-ITR Bot",
            "Disclaimer": (
                "This JSON is generated for upload to incometax.gov.in. "
                "Please review all values before submitting. "
                "Verify with a Chartered Accountant."
            ),
        },
    }


def generate_itr4_efiling_json(
    inp: ITR4Input,
    result: ITRResult,
    personal_info: dict | None = None,
) -> dict:
    """
    Generate ITR-4 JSON compatible with the incometax.gov.in e-filing portal.

    Parameters
    ----------
    inp : ITR4Input
    result : ITRResult
    personal_info : dict, optional
        Extra personal details.
    """
    pi = personal_info or {}
    rec = result.old_regime if result.recommended_regime == "old" else result.new_regime
    opt_out_new = "Y" if result.recommended_regime == "old" else "N"

    deemed_profit = inp.gross_turnover * inp.presumptive_rate / 100
    professional_income = inp.gross_receipts * inp.professional_rate / 100
    total_business = deemed_profit + professional_income
    total_deductions = rec.total_deductions
    taxable_income = rec.taxable_income
    total_paid = inp.tds_total + inp.advance_tax

    return {
        "Form_ITR4": {
            "FormName": "ITR-4",
            "Description": (
                "For Individuals, HUFs and Firms (other than LLP) having income "
                "from Business or Profession computed under sections 44AD, 44ADA, 44AE"
            ),
            "AssessmentYear": inp.assessment_year.replace("-", ""),
            "SchemaVer": "Ver1.0",
            "FormVer": "Ver1.0",
        },
        "PersonalInfo": {
            "AssesseeName": {
                "FirstName": pi.get("firstName", inp.name or ""),
                "MiddleName": pi.get("middleName", ""),
                "SurNameOrOrgName": pi.get("surName", ""),
            },
            "PAN": inp.pan,
            "DOB": pi.get("dob", ""),
            "AadhaarCardNo": pi.get("aadhaar", ""),
            "Address": pi.get("address", {}),
        },
        "FilingStatus": {
            "ReturnFileSec": 11,
            "OptOutNewTaxRegime": opt_out_new,
        },
        "ScheduleBP": {
            "NatOfBus44AD": {
                "GrossReceipts": _fl(inp.gross_turnover),
                "PresumptiveRate": _fl(inp.presumptive_rate),
                "DeemedProfit": _fl(deemed_profit),
            },
            "NatOfBus44ADA": {
                "GrossReceipts": _fl(inp.gross_receipts),
                "PresumptiveRate": _fl(inp.professional_rate),
                "ProfessionalIncome": _fl(professional_income),
            },
            "ProfitFromBP": _fl(total_business),
        },
        "ITR4_IncomeDeductions": {
            "IncomeFromBP": _fl(total_business),
            "IncomeFromSalary": _fl(inp.salary_income),
            "IncomeFromHP": _fl(inp.house_property_income),
            "IncomeOthSrc": _fl(inp.other_income),
            "GrossTotIncome": _fl(rec.gross_total_income),
            "DeductUndChapVIA": {
                "Section80C": _fl(inp.section_80c),
                "Section80D": _fl(inp.section_80d),
                "OtherDeductions": _fl(inp.other_deductions),
                "TotalChapVIADeductions": _fl(total_deductions),
            },
            "TotalIncome": _fl(taxable_income),
        },
        "ITR4_TaxComputation": {
            "TotalTaxPayable": _fl(rec.tax_on_income),
            "Rebate87A": _fl(rec.rebate_87a),
            "TaxPayableOnTI": _fl(rec.tax_on_income - rec.rebate_87a),
            "SurchargeOnAboveCrore": _fl(rec.surcharge),
            "EducationCess": _fl(rec.health_cess),
            "GrossTaxLiability": _fl(rec.total_tax_liability),
            "TotalTaxesPaid": {
                "TDS": _fl(inp.tds_total),
                "TCS": 0.0,
                "AdvanceTax": _fl(inp.advance_tax),
                "TotalPaid": _fl(total_paid),
            },
            "BalTaxPayable": _fl(rec.tax_payable),
        },
        "Verification": {
            "Declaration": (
                "I declare that the information given in this return is correct "
                "and complete."
            ),
            "GeneratedAt": datetime.now(timezone.utc).isoformat(),
            "GeneratedBy": "GST-ITR Bot",
            "Disclaimer": (
                "This JSON is generated for upload to incometax.gov.in. "
                "Please review all values before submitting. "
                "Verify with a Chartered Accountant."
            ),
        },
    }
