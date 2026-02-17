# app/infrastructure/external/tax_rate_ai.py
"""
OpenAI-powered tax rate fetcher — Layer 3 (cold fetch).

Calls GPT-4o with structured prompts to retrieve the latest Indian
income-tax slabs and GST rates, validates the response, and returns
domain config objects.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation

from app.config.settings import settings
from app.domain.models.tax_rate_config import GSTRateConfig, ITRSlabConfig
from app.infrastructure.external.openai_client import _get_client

logger = logging.getLogger("tax_rate_ai")

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

ITR_SLAB_SYSTEM_PROMPT = """\
You are an Indian income tax expert. Return the CURRENT income-tax slabs and \
parameters for the specified Assessment Year as a JSON object.

Return a JSON object with EXACTLY these fields:
{
  "assessment_year": "<the AY>",
  "old_regime_slabs": [[upper_limit_or_null, rate_percent], ...],
  "old_regime_senior_slabs": [[upper_limit_or_null, rate_percent], ...],
  "old_regime_super_senior_slabs": [[upper_limit_or_null, rate_percent], ...],
  "new_regime_slabs": [[upper_limit_or_null, rate_percent], ...],
  "rebate_87a_old_limit": number,
  "rebate_87a_old_max": number,
  "rebate_87a_new_limit": number,
  "rebate_87a_new_max": number,
  "section_80c_max": number,
  "section_80d_max_self": number,
  "section_80d_max_senior": number,
  "section_80d_max_parents": number,
  "section_80d_max_total": number,
  "section_80tta_max": number,
  "section_80ccd_1b_max": number,
  "standard_deduction_salary": number,
  "standard_deduction_new_regime": number,
  "surcharge_slabs": [[lower, upper_or_null, rate_percent], ...],
  "cess_rate": number
}

CRITICAL:
- Use the latest Union Budget / Finance Act amendments applicable to the AY.
- All monetary numbers are in INR (not lakhs). E.g., 2.5 lakh = 250000.
- Rates are percentages (e.g. 5 means 5%, NOT 0.05).
- Each slab array is ordered from lowest to highest bracket.
- The last slab in each array MUST have null as upper_limit (unbounded).
- Senior citizen = 60-80 years, Super senior = 80+ years.
- Return ONLY the JSON, no explanation.\
"""

GST_RATE_SYSTEM_PROMPT = """\
You are an Indian GST expert. Return all VALID standard GST rates currently \
in effect in India as a JSON object.

Return:
{
  "valid_rates": [0, 0.1, 0.25, 1.5, 3, 5, 6, 7.5, 12, 14, 18, 28]
}

Include all standard rates per the latest GST Council decisions. Rates are \
percentages. Include 0 for exempt supplies.
Return ONLY the JSON, no explanation.\
"""


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------

async def fetch_itr_slabs_from_ai(assessment_year: str) -> ITRSlabConfig | None:
    """Fetch ITR slab configuration from OpenAI GPT-4o.

    Returns None on any failure (API error, validation failure, timeout).
    """
    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": ITR_SLAB_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Return income-tax slabs and parameters for Assessment Year {assessment_year}.",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)

        if not _validate_itr_config(data):
            logger.warning("ITR slab validation failed for AI response: %s", raw[:500])
            return None

        config = ITRSlabConfig.from_dict(data)
        config.source = "openai"
        logger.info("Fetched ITR slabs from OpenAI for AY %s", assessment_year)
        return config

    except Exception:
        logger.exception("Failed to fetch ITR slabs from OpenAI for AY %s", assessment_year)
        return None


async def fetch_gst_rates_from_ai() -> GSTRateConfig | None:
    """Fetch GST rate set from OpenAI GPT-4o.

    Returns None on any failure.
    """
    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": GST_RATE_SYSTEM_PROMPT},
                {"role": "user", "content": "Return all valid GST rates currently in effect in India."},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=500,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)

        if not _validate_gst_config(data):
            logger.warning("GST rate validation failed for AI response: %s", raw[:500])
            return None

        config = GSTRateConfig.from_dict(data)
        config.source = "openai"
        logger.info("Fetched GST rates from OpenAI: %s", sorted(config.valid_rates))
        return config

    except Exception:
        logger.exception("Failed to fetch GST rates from OpenAI")
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_itr_config(data: dict) -> bool:
    """Structural validation of AI-returned ITR config."""
    try:
        slab_keys = [
            "old_regime_slabs",
            "old_regime_senior_slabs",
            "old_regime_super_senior_slabs",
            "new_regime_slabs",
        ]
        for key in slab_keys:
            slabs = data.get(key)
            if not isinstance(slabs, list) or len(slabs) < 2:
                logger.warning("Validation: %s missing or too short", key)
                return False
            # Last entry must have null upper limit
            if slabs[-1][0] is not None:
                logger.warning("Validation: %s last slab upper limit is not null", key)
                return False
            # All rates must be non-negative numbers
            for entry in slabs:
                rate = float(entry[1])
                if rate < 0 or rate > 100:
                    logger.warning("Validation: %s has invalid rate %s", key, rate)
                    return False

        # Surcharge slabs
        surcharge = data.get("surcharge_slabs")
        if not isinstance(surcharge, list) or len(surcharge) < 1:
            logger.warning("Validation: surcharge_slabs missing or empty")
            return False

        # Required scalar fields
        required_scalars = [
            "rebate_87a_old_limit", "rebate_87a_old_max",
            "rebate_87a_new_limit", "rebate_87a_new_max",
            "section_80c_max", "cess_rate",
        ]
        for key in required_scalars:
            val = data.get(key)
            if val is None:
                logger.warning("Validation: required field %s is missing", key)
                return False
            if float(val) < 0:
                logger.warning("Validation: %s is negative", key)
                return False

        return True

    except (TypeError, ValueError, IndexError, KeyError) as e:
        logger.warning("Validation error: %s", e)
        return False


def _validate_gst_config(data: dict) -> bool:
    """Structural validation of AI-returned GST config."""
    try:
        rates = data.get("valid_rates")
        if not isinstance(rates, list) or len(rates) < 3:
            logger.warning("Validation: valid_rates missing or too short")
            return False
        for r in rates:
            if float(r) < 0 or float(r) > 50:
                logger.warning("Validation: GST rate %s out of range", r)
                return False
        return True
    except (TypeError, ValueError) as e:
        logger.warning("GST validation error: %s", e)
        return False
