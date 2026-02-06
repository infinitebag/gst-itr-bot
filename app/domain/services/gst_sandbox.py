# app/domain/services/gst_sandbox.py
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings

# You can configure these in your settings / env
_BASE_URL = (
    getattr(settings, "GST_SANDBOX_BASE_URL", "").rstrip("/")
    or "https://httpbin.org/post"
)
_TIMEOUT = float(getattr(settings, "GST_SANDBOX_TIMEOUT", 10.0))
_API_KEY = getattr(settings, "GST_SANDBOX_API_KEY", "")  # if you have one


async def _post_to_sandbox(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Generic helper to POST JSON to GST sandbox.
    Returns a dict even on HTTP error, so callers can show user-friendly text.
    """
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    headers = {
        "Content-Type": "application/json",
    }
    if _API_KEY:
        headers["x-api-key"] = _API_KEY

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            return {
                "status": "ERROR",
                "error": str(e),
                "status_code": None,
            }

    try:
        resp.raise_for_status()
    except httpx.HTTPError as e:
        # Non-2xx: still return JSON-ish structure
        body_text = resp.text[:500]
        return {
            "status": "ERROR",
            "error": str(e),
            "status_code": resp.status_code,
            "body": body_text,
        }

    try:
        data = resp.json()
    except ValueError:
        data = {"status": "OK", "raw": resp.text}

    return data


async def submit_gstr1_to_sandbox(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Submit GSTR-1 JSON to sandbox.
    `payload` should already be a GSTR-1 JSON dict (from make_gstr1_json).
    """
    return await _post_to_sandbox("gstr1", payload)


async def submit_gstr3b_to_sandbox(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Submit GSTR-3B JSON to sandbox.
    `payload` should already be a GSTR-3B JSON dict (from make_gstr3b_json).
    """
    return await _post_to_sandbox("gstr3b", payload)
