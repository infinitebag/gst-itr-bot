# app/infrastructure/external/einvoice_client.py
"""
MasterGST / WhiteBooks e-Invoice API client.

Handles authentication (username/password), IRN generation, cancellation,
e-WayBill generation from IRN, and B2C QR code generation.

API base path: /einvoice/
Authentication: GET /einvoice/authenticate (username + password in headers)

All endpoints require:
  Headers: ip_address, client_id, client_secret, username, gstin
  Query: email
  Authenticated endpoints also require: auth-token
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.core.config import settings

logger = logging.getLogger("einvoice_client")

_TIMEOUT = 30


class EInvoiceError(Exception):
    """Raised when e-Invoice API returns an error."""

    def __init__(self, message: str, status_code: int = 0, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class EInvoiceClient:
    """Client for MasterGST / WhiteBooks e-Invoice API."""

    def __init__(self) -> None:
        self.base = settings.MASTERGST_EINVOICE_BASE_URL.rstrip("/")
        # Own credentials, falling back to shared GST API credentials
        self.client_id = settings.MASTERGST_EINVOICE_CLIENT_ID or settings.MASTERGST_CLIENT_ID
        self.client_secret = settings.MASTERGST_EINVOICE_CLIENT_SECRET or settings.MASTERGST_CLIENT_SECRET
        self.email = settings.MASTERGST_EMAIL
        self.username = settings.MASTERGST_EINVOICE_USERNAME
        self.password = settings.MASTERGST_EINVOICE_PASSWORD
        self.ip_address = settings.MASTERGST_IP_ADDRESS or "127.0.0.1"

    @classmethod
    def is_configured(cls) -> bool:
        """Check if e-Invoice API credentials are available."""
        has_client_id = bool(settings.MASTERGST_EINVOICE_CLIENT_ID or settings.MASTERGST_CLIENT_ID)
        has_client_secret = bool(settings.MASTERGST_EINVOICE_CLIENT_SECRET or settings.MASTERGST_CLIENT_SECRET)
        return bool(
            settings.MASTERGST_EINVOICE_BASE_URL
            and has_client_id
            and has_client_secret
            and settings.MASTERGST_EINVOICE_USERNAME
            and settings.MASTERGST_EINVOICE_PASSWORD
            and settings.MASTERGST_EMAIL
        )

    def _base_headers(self) -> Dict[str, str]:
        """Base headers for all e-Invoice API calls."""
        return {
            "Content-Type": "application/json",
            "ip_address": self.ip_address,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
        }

    def _auth_headers(self, gstin: str, auth_token: str) -> Dict[str, str]:
        """Headers for authenticated e-Invoice API calls."""
        h = self._base_headers()
        h["gstin"] = gstin
        h["auth-token"] = auth_token
        return h

    def _email_params(self, **extra) -> Dict[str, str]:
        """Query params — email is required on every call."""
        params = {"email": self.email}
        params.update(extra)
        return params

    async def _request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        params: Dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request to e-Invoice API."""
        url = f"{self.base}{path}"
        logger.info("e-Invoice %s %s", method, path)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.request(
                    method, url, headers=headers, json=json_body, params=params,
                )
                r.raise_for_status()
                data = r.json()
                logger.info("e-Invoice response status=%d", r.status_code)
                return data
            except httpx.HTTPStatusError as exc:
                body = {}
                try:
                    body = exc.response.json()
                except Exception:
                    pass
                logger.error("e-Invoice HTTP error: %s %s -> %d", method, path, exc.response.status_code)
                raise EInvoiceError(
                    f"e-Invoice API error: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                    response=body,
                ) from exc
            except httpx.TimeoutException as exc:
                raise EInvoiceError("e-Invoice API timeout") from exc
            except Exception as exc:
                raise EInvoiceError(f"e-Invoice unexpected error: {exc}") from exc

    # ----------------------------------------------------------------
    # Authentication
    # ----------------------------------------------------------------

    async def authenticate(self, gstin: str) -> str:
        """
        Authenticate with e-Invoice API.

        Uses username/password as HEADERS (NOT OTP flow like GST API).
        Returns auth_token string.
        """
        if not self.username or not self.password:
            raise EInvoiceError("e-Invoice username/password not configured")

        headers = self._base_headers()
        headers["gstin"] = gstin
        headers["username"] = self.username
        headers["password"] = self.password

        resp = await self._request(
            "GET",
            "/einvoice/authenticate",
            headers=headers,
            params=self._email_params(),
        )

        # Response puts token under data.AuthToken (capital A/T)
        data = resp.get("data", {}) or {}
        auth_token = (
            data.get("AuthToken")
            or data.get("auth_token")
            or resp.get("AuthToken")
            or resp.get("auth_token")
            or ""
        )
        if not auth_token:
            raise EInvoiceError("Failed to obtain e-Invoice auth_token", response=resp)

        logger.info("Authenticated with e-Invoice API for GSTIN %s", gstin)
        return auth_token

    # ----------------------------------------------------------------
    # IRN (Invoice Reference Number)
    # ----------------------------------------------------------------

    async def generate_irn(
        self, gstin: str, auth_token: str, invoice_data: dict,
    ) -> Dict[str, Any]:
        """
        Generate an IRN (Invoice Reference Number) for an e-Invoice.

        Args:
            gstin: Supplier GSTIN
            auth_token: Token from authenticate()
            invoice_data: e-Invoice payload (seller, buyer, items, etc.)

        Returns:
            Response containing IRN, signed invoice, QR code, etc.
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            "/einvoice/type/GENERATE/version/V1_03",
            headers=headers,
            params=self._email_params(),
            json_body=invoice_data,
        )

    async def get_irn_details(
        self, gstin: str, auth_token: str, irn: str,
    ) -> Dict[str, Any]:
        """Get e-Invoice details for a given IRN."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/einvoice/type/GETIRN/version/V1_03",
            headers=headers,
            params=self._email_params(param1=irn, supplier_gstn=gstin),
        )

    async def get_irn_by_doc(
        self,
        gstin: str,
        auth_token: str,
        doc_num: str,
        doc_date: str,
    ) -> Dict[str, Any]:
        """Get IRN details by document number and date."""
        headers = self._auth_headers(gstin, auth_token)
        headers["docnum"] = doc_num
        headers["docdate"] = doc_date
        return await self._request(
            "GET",
            "/einvoice/type/GETIRNBYDOCDETAILS/version/V1_03",
            headers=headers,
            params=self._email_params(param1=gstin, supplier_gstn=gstin),
        )

    async def cancel_irn(
        self,
        gstin: str,
        auth_token: str,
        cancel_data: dict,
    ) -> Dict[str, Any]:
        """
        Cancel an IRN.

        Args:
            cancel_data: Dict with Irn, CnlRsn (1=Duplicate, 2=Data Error),
                         CnlRem (cancellation reason text)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            "/einvoice/type/CANCEL/version/V1_03",
            headers=headers,
            params=self._email_params(),
            json_body=cancel_data,
        )

    async def get_rejected_irns(
        self, gstin: str, auth_token: str,
    ) -> Dict[str, Any]:
        """Get list of rejected IRNs."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/einvoice/type/GETREJECTEDIRNS/version/V1_03",
            headers=headers,
            params=self._email_params(param1=gstin, supplier_gstn=gstin),
        )

    # ----------------------------------------------------------------
    # e-WayBill via e-Invoice (using IRN)
    # ----------------------------------------------------------------

    async def generate_ewaybill_from_irn(
        self,
        gstin: str,
        auth_token: str,
        ewaybill_data: dict,
    ) -> Dict[str, Any]:
        """Generate an e-WayBill using an existing IRN."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            "/einvoice/type/GENERATE_EWAYBILL/version/V1_03",
            headers=headers,
            params=self._email_params(),
            json_body=ewaybill_data,
        )

    async def get_ewaybill_by_irn(
        self, gstin: str, auth_token: str, irn: str,
    ) -> Dict[str, Any]:
        """Get e-WayBill details by IRN."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/einvoice/type/GETEWAYBILLIRN/version/V1_03",
            headers=headers,
            params=self._email_params(param1=irn, supplier_gstn=gstin),
        )

    # ----------------------------------------------------------------
    # GSTN & QR Code
    # ----------------------------------------------------------------

    async def get_gstn_details(
        self, gstin: str, auth_token: str, target_gstin: str,
    ) -> Dict[str, Any]:
        """Get GSTN details for a given GSTIN via e-Invoice portal."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/einvoice/type/GSTNDETAILS/version/V1_03",
            headers=headers,
            params=self._email_params(param1=target_gstin),
        )
