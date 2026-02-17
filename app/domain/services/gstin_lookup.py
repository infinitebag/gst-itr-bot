# app/domain/services/gstin_lookup.py
"""
GSTIN details lookup service.

Calls the GST public/MasterGST API to fetch business details for a given
GSTIN (legal name, state, status).  Results are cached in Redis for 24 h.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("gstin_lookup")

_CACHE_TTL = 86_400  # 24 hours


async def lookup_gstin_details(gstin: str) -> Optional[Dict[str, Any]]:
    """Fetch business details for a GSTIN.

    Returns
    -------
    dict or None
        ``{"legal_name": "...", "state": "...", "status": "Active/Inactive"}``
        or *None* on failure / not found.
    """
    gstin = gstin.strip().upper()

    # 1. Check Redis cache first
    cached = await _get_from_cache(gstin)
    if cached is not None:
        logger.debug("gstin_lookup: cache hit for %s", gstin)
        return cached

    # 2. Call external API
    details = await _call_gst_api(gstin)
    if details:
        await _set_cache(gstin, details)
        return details

    return None


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

async def _call_gst_api(gstin: str) -> Optional[Dict[str, Any]]:
    """Call MasterGST / GST public API.

    Uses ``settings.MASTERGST_API_URL`` if configured, otherwise returns None
    (the caller should fall back to asking the user for details).
    """
    api_url = getattr(settings, "MASTERGST_API_URL", None)
    api_key = getattr(settings, "MASTERGST_API_KEY", None)

    if not api_url:
        logger.info("gstin_lookup: no MASTERGST_API_URL configured, skipping API call")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = await client.get(
                f"{api_url.rstrip('/')}/commonapi/v1.1/search",
                params={"gstin": gstin, "aspid": api_key or ""},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            # Parse MasterGST response format
            if data.get("error") or not data.get("data"):
                logger.warning("gstin_lookup: API returned error for %s: %s", gstin, data.get("message"))
                return None

            gst_data = data["data"]
            return {
                "legal_name": gst_data.get("lgnm") or gst_data.get("tradeNam") or "",
                "state": gst_data.get("pradr", {}).get("addr", {}).get("stcd") or _state_from_gstin(gstin),
                "status": gst_data.get("sts") or "Unknown",
            }
    except Exception:
        logger.exception("gstin_lookup: API call failed for %s", gstin)
        return None


def _state_from_gstin(gstin: str) -> str:
    """Extract state code from GSTIN (first 2 digits) and map to state name."""
    _STATE_CODES = {
        "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
        "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
        "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
        "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
        "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
        "16": "Tripura", "17": "Meghalaya", "18": "Assam",
        "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
        "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
        "26": "Dadra & Nagar Haveli", "27": "Maharashtra", "28": "Andhra Pradesh",
        "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
        "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
        "35": "Andaman & Nicobar", "36": "Telangana", "37": "Andhra Pradesh (New)",
        "38": "Ladakh", "97": "Other Territory",
    }
    code = gstin[:2] if len(gstin) >= 2 else ""
    return _STATE_CODES.get(code, f"State Code {code}")


async def _get_from_cache(gstin: str) -> Optional[Dict[str, Any]]:
    """Read GSTIN details from Redis cache."""
    try:
        from app.infrastructure.cache.session_cache import redis_pool
        r = redis_pool()
        raw = await r.get(f"gstin:details:{gstin}")
        if raw:
            return json.loads(raw)
    except Exception:
        logger.debug("gstin_lookup: cache read failed for %s", gstin, exc_info=True)
    return None


async def _set_cache(gstin: str, details: Dict[str, Any]) -> None:
    """Write GSTIN details to Redis cache."""
    try:
        from app.infrastructure.cache.session_cache import redis_pool
        r = redis_pool()
        await r.setex(f"gstin:details:{gstin}", _CACHE_TTL, json.dumps(details))
    except Exception:
        logger.debug("gstin_lookup: cache write failed for %s", gstin, exc_info=True)
