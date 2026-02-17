# app/infrastructure/external/mastergst_client.py
"""
MasterGST / WhiteBooks GST API client.

Handles authentication (OTP flow), GSTR-3B and GSTR-1 save/submit/file,
NIL filing, return status, and GSTR-2A/2B retrieval against the
MasterGST sandbox (or production) environment.

API docs: https://whitebooks.in  (sign up → Developer → Credentials)

Authentication flow (GST API):
  1. GET /authentication/otprequest  → triggers OTP to taxpayer
  2. GET /authentication/authtoken   → exchange OTP for auth token
     Sandbox always accepts OTP = 575757

Required headers for every call:
  client_id, client_secret, gst_username, state_cd, ip_address

Required query param for every call:
  email
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("mastergst_client")

# Timeout for all MasterGST API calls (seconds)
_TIMEOUT = 30


class MasterGSTError(Exception):
    """Raised when MasterGST API returns an error."""

    def __init__(self, message: str, status_code: int = 0, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class MasterGSTClient:
    """
    Client for MasterGST / WhiteBooks GST API.

    Uses the actual API endpoints from the official Postman/OpenAPI spec:
      - Authentication: /authentication/otprequest, /authentication/authtoken
      - GSTR-3B: /gstr3b/retsave (PUT), /gstr3b/retfile (POST), /gstr3b/retsum (GET)
      - GSTR-1: /gstr1/retsave (PUT), /gstr1/retfile (POST), /gstr1/retsum (GET)
    """

    def __init__(self) -> None:
        self.base = settings.MASTERGST_BASE_URL.rstrip("/")
        self.client_id = settings.MASTERGST_CLIENT_ID
        self.client_secret = settings.MASTERGST_CLIENT_SECRET
        self.email = settings.MASTERGST_EMAIL
        self.gst_username = settings.MASTERGST_GST_USERNAME
        self.state_cd = settings.MASTERGST_STATE_CD
        self.ip_address = settings.MASTERGST_IP_ADDRESS or "127.0.0.1"
        self.otp_default = settings.MASTERGST_OTP_DEFAULT

    def _common_headers(self) -> Dict[str, str]:
        """Headers required on every API call (except public endpoints)."""
        return {
            "Content-Type": "application/json",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "gst_username": self.gst_username,
            "state_cd": self.state_cd,
            "ip_address": self.ip_address,
        }

    def _auth_headers(
        self,
        gstin: str,
        auth_token: str,
        ret_period: str = "",
    ) -> Dict[str, str]:
        """Headers for authenticated GST data endpoints."""
        h = self._common_headers()
        h["gstin"] = gstin
        h["auth-token"] = auth_token
        if ret_period:
            h["ret_period"] = ret_period
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
        """Make an HTTP request to MasterGST API."""
        url = f"{self.base}{path}"

        logger.info("MasterGST %s %s", method, path)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.request(
                    method, url, headers=headers, json=json_body, params=params,
                )
                r.raise_for_status()

                # Handle empty or non-JSON responses gracefully
                raw = r.text.strip()
                if not raw:
                    logger.warning(
                        "MasterGST returned empty body: %s %s (status=%d)",
                        method, path, r.status_code,
                    )
                    return {"status_cd": "1", "status_desc": "Success (empty body)", "_empty": True}

                try:
                    data = r.json()
                except ValueError:
                    logger.warning(
                        "MasterGST returned non-JSON body: %s %s (status=%d, body=%.200s)",
                        method, path, r.status_code, raw,
                    )
                    return {"status_cd": "1", "status_desc": "Success (non-JSON)", "_raw": raw[:500]}

                logger.info("MasterGST response status=%d", r.status_code)
                return data
            except httpx.HTTPStatusError as exc:
                body = {}
                try:
                    body = exc.response.json()
                except Exception:
                    pass
                logger.error(
                    "MasterGST HTTP error: %s %s -> %d %s",
                    method, path, exc.response.status_code, body,
                )
                raise MasterGSTError(
                    f"MasterGST API error: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                    response=body,
                ) from exc
            except httpx.TimeoutException as exc:
                logger.error("MasterGST timeout: %s %s", method, path)
                raise MasterGSTError("MasterGST API timeout") from exc
            except Exception as exc:
                logger.exception("MasterGST unexpected error: %s %s", method, path)
                raise MasterGSTError(f"MasterGST unexpected error: {exc}") from exc

    # ----------------------------------------------------------------
    # Authentication (OTP flow)
    # ----------------------------------------------------------------

    async def authenticate(self, gstin: str, username: str | None = None) -> str:
        """
        Authenticate with MasterGST/WhiteBooks using the 2-step OTP flow.

        Step 1: GET /authentication/otprequest  → triggers OTP (pass gstin, username, otp)
        Step 2: GET /authentication/authtoken   → exchange OTP for auth token

        Sandbox always accepts OTP = 575757.
        Returns the auth_token string.
        """
        username = username or self.gst_username
        if not username:
            raise MasterGSTError("MASTERGST_GST_USERNAME not configured")
        if not self.email:
            raise MasterGSTError("MASTERGST_EMAIL not configured")

        headers = self._common_headers()

        # Step 1: Request OTP — must include gstin, username, otp as query params
        otp_resp = await self._request(
            "GET",
            "/authentication/otprequest",
            headers=headers,
            params=self._email_params(
                gstin=gstin,
                username=username,
                otp=self.otp_default,
            ),
        )
        logger.info("OTP requested for GSTIN %s: %s", gstin, otp_resp.get("status_cd"))

        # Extract txn token from OTP response (needed for auth token request)
        txn = (
            otp_resp.get("txn")
            or (otp_resp.get("header") or {}).get("txn", "")
            or otp_resp.get("data", {}).get("txn", "")
            or ""
        )

        # Step 2: Get auth token using OTP
        auth_headers = self._common_headers()
        if txn:
            auth_headers["txn"] = txn

        auth_resp = await self._request(
            "GET",
            "/authentication/authtoken",
            headers=auth_headers,
            params=self._email_params(
                gstin=gstin,
                username=username,
                otp=self.otp_default,
            ),
        )

        data = auth_resp.get("data", {}) or {}
        auth_token = (
            auth_resp.get("auth_token")
            or data.get("auth_token")
            or data.get("auth-token")
            or ""
        )

        # Sandbox fallback: if auth succeeded (status_cd="1") but no real token, use placeholder
        status_cd = str(auth_resp.get("status_cd", "0"))
        if not auth_token and status_cd == "1":
            auth_token = f"sandbox-{txn}" if txn else "sandbox-token"
            logger.info("MasterGST sandbox auth succeeded (no real token returned)")

        if not auth_token:
            raise MasterGSTError(
                "Failed to obtain auth_token from MasterGST",
                response=auth_resp,
            )

        logger.info("Authenticated with MasterGST for GSTIN %s", gstin)
        return auth_token

    async def refresh_token(self, gstin: str, auth_token: str) -> str:
        """Refresh an existing auth token."""
        headers = self._auth_headers(gstin, auth_token)
        resp = await self._request(
            "GET",
            "/authentication/refreshtoken",
            headers=headers,
            params=self._email_params(),
        )
        new_token = (
            resp.get("auth_token")
            or resp.get("data", {}).get("auth_token", "")
            or auth_token
        )
        return new_token

    async def logout(self, gstin: str, auth_token: str) -> Dict[str, Any]:
        """Logout and invalidate auth token."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/authentication/logout",
            headers=headers,
            params=self._email_params(),
        )

    # ----------------------------------------------------------------
    # Public endpoints (no auth required)
    # ----------------------------------------------------------------

    async def search_taxpayer(self, gstin: str) -> Dict[str, Any]:
        """Search taxpayer details by GSTIN (public, no auth needed)."""
        headers = {
            "Content-Type": "application/json",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        return await self._request(
            "GET",
            "/public/search",
            headers=headers,
            params=self._email_params(gstin=gstin),
        )

    async def track_return(self, gstin: str, fy: str, return_type: str) -> Dict[str, Any]:
        """View and track return filing status (public, no auth needed)."""
        headers = {
            "Content-Type": "application/json",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        return await self._request(
            "GET",
            "/public/rettrack",
            headers=headers,
            params=self._email_params(gstin=gstin, fy=fy, type=return_type),
        )

    # ----------------------------------------------------------------
    # GSTR-3B
    # ----------------------------------------------------------------

    async def get_gstr3b_summary(
        self, gstin: str, fp: str, auth_token: str,
    ) -> Dict[str, Any]:
        """Get GSTR-3B summary for a period."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/gstr3b/retsum",
            headers=headers,
            params=self._email_params(gstin=gstin, retperiod=fp),
        )

    async def save_gstr3b(
        self,
        gstin: str,
        fp: str,
        payload: Dict[str, Any],
        auth_token: str,
    ) -> Dict[str, Any]:
        """
        Save GSTR-3B draft to MasterGST.

        Uses PUT /gstr3b/retsave as per API spec.
        """
        headers = self._auth_headers(gstin, auth_token, ret_period=fp)
        return await self._request(
            "PUT",
            "/gstr3b/retsave",
            headers=headers,
            params=self._email_params(),
            json_body=payload,
        )

    async def submit_gstr3b(
        self,
        gstin: str,
        fp: str,
        auth_token: str,
        pan: str = "",
    ) -> Dict[str, Any]:
        """
        File (submit) saved GSTR-3B on MasterGST.

        Uses POST /gstr3b/retfile. Must call save_gstr3b() first.
        """
        headers = self._auth_headers(gstin, auth_token, ret_period=fp)
        return await self._request(
            "POST",
            "/gstr3b/retfile",
            headers=headers,
            params=self._email_params(pan=pan) if pan else self._email_params(),
            json_body={"gstin": gstin, "ret_period": fp},
        )

    async def file_nil_gstr3b(
        self,
        gstin: str,
        fp: str,
        auth_token: str,
    ) -> Dict[str, Any]:
        """File a NIL GSTR-3B return (save + submit with zero values)."""
        nil_payload = {
            "gstin": gstin,
            "ret_period": fp,
            "sup_details": {
                "osup_det": {"txval": 0, "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                "osup_zero": {"txval": 0, "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                "osup_nil_exmp": {"txval": 0},
                "osup_nongst": {"txval": 0},
                "isup_rev": {"txval": 0, "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
            },
            "itc_elg": {
                "itc_avl": [
                    {"ty": "IMPG", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                    {"ty": "IMPS", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                    {"ty": "ISRC", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                    {"ty": "ISD", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                    {"ty": "OTH", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                ],
                "itc_rev": [
                    {"ty": "RUL", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                    {"ty": "OTH", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                ],
                "itc_net": {"igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                "itc_inelg": [
                    {"ty": "RUL", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                    {"ty": "OTH", "igst": 0, "cgst": 0, "sgst": 0, "cess": 0},
                ],
            },
            "inward_sup": {
                "isup_details": [
                    {"ty": "GST", "inter": 0, "intra": 0},
                    {"ty": "NONGST", "inter": 0, "intra": 0},
                ]
            },
            "intr_ltfee": {"intr_details": {"igst": 0, "cgst": 0, "sgst": 0, "cess": 0}},
        }

        # Save NIL return first
        await self.save_gstr3b(gstin, fp, nil_payload, auth_token)

        # Then file/submit
        return await self.submit_gstr3b(gstin, fp, auth_token)

    # ----------------------------------------------------------------
    # GSTR-1
    # ----------------------------------------------------------------

    async def get_gstr1_summary(
        self, gstin: str, fp: str, auth_token: str,
    ) -> Dict[str, Any]:
        """Get GSTR-1 summary for a period."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/gstr1/retsum",
            headers=headers,
            params=self._email_params(gstin=gstin, retperiod=fp),
        )

    async def save_gstr1(
        self,
        gstin: str,
        fp: str,
        payload: Dict[str, Any],
        auth_token: str,
    ) -> Dict[str, Any]:
        """
        Save GSTR-1 draft to MasterGST.

        Uses PUT /gstr1/retsave as per API spec.
        """
        headers = self._auth_headers(gstin, auth_token, ret_period=fp)
        return await self._request(
            "PUT",
            "/gstr1/retsave",
            headers=headers,
            params=self._email_params(),
            json_body=payload,
        )

    async def submit_gstr1(
        self,
        gstin: str,
        fp: str,
        auth_token: str,
        pan: str = "",
    ) -> Dict[str, Any]:
        """
        File (submit) saved GSTR-1 on MasterGST.

        Uses POST /gstr1/retfile. Must call save_gstr1() first.
        """
        headers = self._auth_headers(gstin, auth_token, ret_period=fp)
        return await self._request(
            "POST",
            "/gstr1/retfile",
            headers=headers,
            params=self._email_params(pan=pan) if pan else self._email_params(),
            json_body={"gstin": gstin, "fp": fp},
        )

    async def file_nil_gstr1(
        self,
        gstin: str,
        fp: str,
        auth_token: str,
    ) -> Dict[str, Any]:
        """File a NIL GSTR-1 return (no outward supplies)."""
        nil_payload = {
            "gstin": gstin,
            "fp": fp,
            "b2b": [],
            "b2cl": [],
            "b2cs": [],
            "cdnr": [],
            "cdnur": [],
            "exp": [],
            "nil": {
                "inv": [
                    {"sply_ty": "INTRB2B", "nil_amt": 0, "expt_amt": 0, "ngsup_amt": 0},
                    {"sply_ty": "INTRB2C", "nil_amt": 0, "expt_amt": 0, "ngsup_amt": 0},
                    {"sply_ty": "INTRAB2B", "nil_amt": 0, "expt_amt": 0, "ngsup_amt": 0},
                    {"sply_ty": "INTRAB2C", "nil_amt": 0, "expt_amt": 0, "ngsup_amt": 0},
                ]
            },
            "hsn": {"data": []},
            "doc_issue": {"doc_det": []},
        }

        # Save first
        await self.save_gstr1(gstin, fp, nil_payload, auth_token)

        # Then file/submit
        return await self.submit_gstr1(gstin, fp, auth_token)

    # ----------------------------------------------------------------
    # GSTR-2A / 2B (Inward supplies — read-only)
    # ----------------------------------------------------------------

    async def get_gstr2a_b2b(
        self, gstin: str, fp: str, auth_token: str,
    ) -> Dict[str, Any]:
        """Get GSTR-2A B2B invoices (purchases from registered dealers)."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/gstr2a/b2b",
            headers=headers,
            params=self._email_params(gstin=gstin, retperiod=fp),
        )

    async def get_gstr2b(
        self, gstin: str, fp: str, auth_token: str,
    ) -> Dict[str, Any]:
        """Get GSTR-2B all details (auto-drafted ITC statement)."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            "/gstr2b/all",
            headers=headers,
            params=self._email_params(gstin=gstin, rtnprd=fp),
        )

    # ----------------------------------------------------------------
    # Return Status
    # ----------------------------------------------------------------

    async def get_return_status(
        self,
        gstin: str,
        fp: str,
        form_type: str,
        auth_token: str,
    ) -> Dict[str, Any]:
        """Check the filing status of a return via public tracking."""
        return await self.track_return(
            gstin=gstin,
            fy=fp,
            return_type=form_type.replace("-", ""),
        )
