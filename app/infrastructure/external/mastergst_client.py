from __future__ import annotations
from typing import Dict, Any
import httpx
from app.config.settings import settings

class MasterGSTClient:
    def __init__(self):
        self.base = settings.MASTERGST_BASE_URL.rstrip("/")
        self.api_key = settings.MASTERGST_API_KEY

    async def validate_gstin(self, gstin: str) -> Dict[str, Any]:
        # Replace endpoint with the exact one you use in your sandbox contract
        url = f"{self.base}/api/v1/gst/validate/{gstin}"
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()

    async def get_taxpayer_profile(self, gstin: str) -> Dict[str, Any]:
        url = f"{self.base}/api/v1/gst/profile/{gstin}"
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()