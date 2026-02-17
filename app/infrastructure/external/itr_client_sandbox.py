import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("itr_sandbox_client")


class ItrSandboxError(Exception):
    """Raised when ITR sandbox API returns an error."""

    def __init__(self, message: str, status_code: int = 0, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class ItrSandboxClient:
    """
    Minimal wrapper for an ITR sandbox.
    You will adapt URLs & payload structure as per the provider (ClearTax, etc.).
    """

    def __init__(self):
        if not settings.ITR_SANDBOX_BASE_URL or not settings.ITR_SANDBOX_API_KEY:
            raise RuntimeError("ITR sandbox not configured")
        self.base_url = settings.ITR_SANDBOX_BASE_URL.rstrip("/")
        self.api_key = settings.ITR_SANDBOX_API_KEY

    @classmethod
    def is_configured(cls) -> bool:
        """Check if ITR sandbox credentials are available."""
        return bool(settings.ITR_SANDBOX_BASE_URL and settings.ITR_SANDBOX_API_KEY)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def prefill_itr1(self, pan: str, assessment_year: str) -> dict:
        url = f"{self.base_url}/itr1/prefill"
        payload = {"pan": pan, "ay": assessment_year}
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                body = {}
                try:
                    body = exc.response.json()
                except Exception:
                    pass
                raise ItrSandboxError(
                    f"ITR-1 prefill failed: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                    response=body,
                ) from exc

    async def submit_itr1(self, payload: dict) -> dict:
        """Submit ITR-1 (salaried income) to the sandbox."""
        url = f"{self.base_url}/itr1/submit"
        logger.info("Submitting ITR-1 to sandbox")
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                body = {}
                try:
                    body = exc.response.json()
                except Exception:
                    pass
                raise ItrSandboxError(
                    f"ITR-1 submission failed: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                    response=body,
                ) from exc

    async def submit_itr4(self, payload: dict) -> dict:
        """Submit ITR-4 (presumptive business/professional income) to the sandbox."""
        url = f"{self.base_url}/itr4/submit"
        logger.info("Submitting ITR-4 to sandbox")
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                body = {}
                try:
                    body = exc.response.json()
                except Exception:
                    pass
                raise ItrSandboxError(
                    f"ITR-4 submission failed: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                    response=body,
                ) from exc
