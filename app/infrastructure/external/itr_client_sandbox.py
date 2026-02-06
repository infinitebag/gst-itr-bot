import httpx

from app.core.config import settings


class ItrSandboxClient:
    """
    Minimal wrapper for an ITR sandbox.
    You will adapt URLs & payload structure as per the provider (ClearTax, etc.).
    """

    def __init__(self):
        if not settings.ITR_SANDBOX_BASE_URL or not settings.ITR_SANDBOX_API_KEY:
            raise RuntimeError("ITR sandbox not configured")
        self.base_url = settings.ITR_SANDBOX_BASE_URL
        self.api_key = settings.ITR_SANDBOX_API_KEY

    async def prefill_itr1(self, pan: str, assessment_year: str) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/itr1/prefill"
        payload = {"pan": pan, "ay": assessment_year}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def submit_itr1(self, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/itr1/submit"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
