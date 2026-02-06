import httpx

from app.core.config import settings


class GstSandboxClient:
    """
    Very simplified client wrapper for NIC GST Sandbox.
    You will adapt endpoint paths & payloads to the actual NIC docs.
    """

    def __init__(self):
        if not settings.GST_SANDBOX_BASE_URL:
            raise RuntimeError("GST_SANDBOX_BASE_URL not configured")

        self.base_url = settings.GST_SANDBOX_BASE_URL
        self.client_id = settings.GST_SANDBOX_CLIENT_ID
        self.client_secret = settings.GST_SANDBOX_CLIENT_SECRET

    async def _get_auth_token(self) -> str:
        """
        Placeholder for auth flow (client_id/secret, OTP=575757, etc.).
        Adapt to actual sandbox API spec.
        """
        # For now, pretend we already have token (or use env var)
        return "dummy_token"

    async def upload_gstr1(self, gstin: str, period: str, payload: dict) -> dict:
        token = await self._get_auth_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/gstr1/{gstin}/{period}/upload"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def upload_gstr3b(self, gstin: str, period: str, payload: dict) -> dict:
        token = await self._get_auth_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/gstr3b/{gstin}/{period}/upload"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
