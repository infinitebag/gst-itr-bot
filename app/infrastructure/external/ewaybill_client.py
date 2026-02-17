# app/infrastructure/external/ewaybill_client.py
"""
MasterGST / WhiteBooks e-WayBill API client.

Handles authentication (username/password), e-WayBill generation, cancellation,
rejection, vehicle updates, validity extension, consolidated EWB, and
multi-vehicle movement.

API base path: /ewaybillapi/v1.03/
Authentication: GET /ewaybillapi/v1.03/authenticate (username + password as query params)

All endpoints require:
  Headers: ip_address, client_id, client_secret, gstin
  Query: email
  Authenticated endpoints also require: authtoken (header)
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.core.config import settings

logger = logging.getLogger("ewaybill_client")

_TIMEOUT = 30
_API_PREFIX = "/ewaybillapi/v1.03"


class EWayBillError(Exception):
    """Raised when e-WayBill API returns an error."""

    def __init__(self, message: str, status_code: int = 0, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class EWayBillClient:
    """Client for MasterGST / WhiteBooks e-WayBill API."""

    def __init__(self) -> None:
        self.base = settings.MASTERGST_EWAYBILL_BASE_URL.rstrip("/")
        # Own credentials, falling back to shared GST API credentials
        self.client_id = settings.MASTERGST_EWAYBILL_CLIENT_ID or settings.MASTERGST_CLIENT_ID
        self.client_secret = settings.MASTERGST_EWAYBILL_CLIENT_SECRET or settings.MASTERGST_CLIENT_SECRET
        self.email = settings.MASTERGST_EMAIL
        self.username = settings.MASTERGST_EWAYBILL_USERNAME
        self.password = settings.MASTERGST_EWAYBILL_PASSWORD
        self.ip_address = settings.MASTERGST_IP_ADDRESS or "127.0.0.1"

    @classmethod
    def is_configured(cls) -> bool:
        """Check if e-WayBill API credentials are available."""
        has_client_id = bool(settings.MASTERGST_EWAYBILL_CLIENT_ID or settings.MASTERGST_CLIENT_ID)
        has_client_secret = bool(settings.MASTERGST_EWAYBILL_CLIENT_SECRET or settings.MASTERGST_CLIENT_SECRET)
        return bool(
            settings.MASTERGST_EWAYBILL_BASE_URL
            and has_client_id
            and has_client_secret
            and settings.MASTERGST_EWAYBILL_USERNAME
            and settings.MASTERGST_EWAYBILL_PASSWORD
            and settings.MASTERGST_EMAIL
        )

    # ----------------------------------------------------------------
    # Header & param helpers
    # ----------------------------------------------------------------

    def _base_headers(self) -> Dict[str, str]:
        """Base headers required on every e-WayBill API call."""
        return {
            "Content-Type": "application/json",
            "ip_address": self.ip_address,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

    def _auth_headers(self, gstin: str, auth_token: str) -> Dict[str, str]:
        """Headers for authenticated e-WayBill API calls."""
        h = self._base_headers()
        h["gstin"] = gstin
        h["authtoken"] = auth_token
        return h

    def _email_params(self, **extra: str) -> Dict[str, str]:
        """Query params — email is required on every call."""
        params: Dict[str, str] = {"email": self.email}
        params.update(extra)
        return params

    # ----------------------------------------------------------------
    # HTTP transport
    # ----------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        params: Dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request to e-WayBill API."""
        url = f"{self.base}{path}"
        logger.info("e-WayBill %s %s", method, path)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.request(
                    method, url, headers=headers, json=json_body, params=params,
                )
                r.raise_for_status()
                data = r.json()
                logger.info("e-WayBill response status=%d", r.status_code)
                return data
            except httpx.HTTPStatusError as exc:
                body: dict = {}
                try:
                    body = exc.response.json()
                except Exception:
                    pass
                logger.error(
                    "e-WayBill HTTP error: %s %s -> %d",
                    method, path, exc.response.status_code,
                )
                raise EWayBillError(
                    f"e-WayBill API error: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                    response=body,
                ) from exc
            except httpx.TimeoutException as exc:
                raise EWayBillError("e-WayBill API timeout") from exc
            except Exception as exc:
                raise EWayBillError(f"e-WayBill unexpected error: {exc}") from exc

    # ----------------------------------------------------------------
    # Authentication
    # ----------------------------------------------------------------

    async def authenticate(self, gstin: str) -> str:
        """
        Authenticate with e-WayBill API.

        Uses username/password as query params (NOT OTP flow like GST API).
        Returns auth_token string.
        """
        if not self.username or not self.password:
            raise EWayBillError("e-WayBill username/password not configured")

        headers = self._base_headers()
        headers["gstin"] = gstin

        resp = await self._request(
            "GET",
            f"{_API_PREFIX}/authenticate",
            headers=headers,
            params=self._email_params(
                username=self.username,
                password=self.password,
            ),
        )

        # Sandbox may return status_cd:"1" with no actual token;
        # Production returns the token under data or authtoken.
        data = resp.get("data", {}) or {}
        auth_token = (
            data.get("authtoken")
            or data.get("auth_token")
            or data.get("AuthToken")
            or resp.get("authtoken")
            or resp.get("auth_token")
            or ""
        )

        # Sandbox fallback: if auth succeeded (status_cd=1) but no token, use a placeholder
        status_cd = str(resp.get("status_cd", "0"))
        if not auth_token and status_cd == "1":
            auth_token = "sandbox-token"
            logger.info("e-WayBill sandbox auth succeeded (no real token returned)")

        if not auth_token:
            raise EWayBillError(
                "Failed to obtain e-WayBill auth_token", response=resp,
            )

        logger.info("Authenticated with e-WayBill API for GSTIN %s", gstin)
        return auth_token

    # ----------------------------------------------------------------
    # Core e-WayBill operations
    # ----------------------------------------------------------------

    async def generate_ewaybill(
        self,
        gstin: str,
        auth_token: str,
        ewaybill_data: dict,
    ) -> Dict[str, Any]:
        """
        Generate a new e-WayBill.

        Args:
            gstin: Supplier/generator GSTIN.
            auth_token: Token from authenticate().
            ewaybill_data: Full e-WayBill payload including:
                - supplyType (O=Outward, I=Inward)
                - subSupplyType, docType, docNo, docDate
                - fromGstin, fromPincode, fromStateCode, actFromStateCode
                - toGstin, toPincode, toStateCode, actToStateCode
                - transDistance, transMode (1=Road, 2=Rail, 3=Air, 4=Ship)
                - vehicleNo, vehicleType, transactionType
                - itemList (array of items with HSN, quantity, tax rates)
                - totInvValue

        Returns:
            Response containing e-WayBill number, validity date, etc.
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/genewaybill",
            headers=headers,
            params=self._email_params(),
            json_body=ewaybill_data,
        )

    async def cancel_ewaybill(
        self,
        gstin: str,
        auth_token: str,
        ewb_no: int,
        cancel_reason_code: int,
        cancel_remarks: str = "",
    ) -> Dict[str, Any]:
        """
        Cancel an existing e-WayBill.

        Args:
            ewb_no: e-WayBill number.
            cancel_reason_code: Reason code for cancellation.
            cancel_remarks: Optional cancellation remarks.
        """
        headers = self._auth_headers(gstin, auth_token)
        body: Dict[str, Any] = {
            "ewbNo": ewb_no,
            "cancelRsnCode": cancel_reason_code,
        }
        if cancel_remarks:
            body["cancelRmrk"] = cancel_remarks

        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/canewb",
            headers=headers,
            params=self._email_params(),
            json_body=body,
        )

    async def reject_ewaybill(
        self,
        gstin: str,
        auth_token: str,
        ewb_no: int,
    ) -> Dict[str, Any]:
        """Reject an e-WayBill generated on you by another party."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/rejewb",
            headers=headers,
            params=self._email_params(),
            json_body={"ewbNo": ewb_no},
        )

    async def update_vehicle(
        self,
        gstin: str,
        auth_token: str,
        vehicle_data: dict,
    ) -> Dict[str, Any]:
        """
        Update Part-B / vehicle number of an e-WayBill.

        Args:
            vehicle_data: Dict with keys:
                - ewbNo (int): e-WayBill number
                - fromPlace (str), fromState (int)
                - transMode (str): 1=Road, 2=Rail, 3=Air, 4=Ship
                - reasonCode (int), reasonRem (str)
                - vehicleNo (str, optional), transDocNo (str, optional),
                  transDocDate (str, optional)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/vehewb",
            headers=headers,
            params=self._email_params(),
            json_body=vehicle_data,
        )

    async def update_transporter(
        self,
        gstin: str,
        auth_token: str,
        ewb_no: int,
        transporter_id: str,
    ) -> Dict[str, Any]:
        """
        Update transporter details for an e-WayBill.

        Args:
            ewb_no: e-WayBill number.
            transporter_id: 15-digit GSTIN or TRANSIN of the transporter.
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/updatetransporter",
            headers=headers,
            params=self._email_params(),
            json_body={"ewbNo": ewb_no, "transporterId": transporter_id},
        )

    async def extend_validity(
        self,
        gstin: str,
        auth_token: str,
        extend_data: dict,
    ) -> Dict[str, Any]:
        """
        Extend the validity of an e-WayBill.

        Args:
            extend_data: Dict with keys:
                - ewbNo (int)
                - fromPlace (str), fromState (int), fromPincode (int)
                - remainingDistance (int)
                - extnRsnCode (int), extnRemarks (str)
                - vehicleNo (str, optional), transDocNo (str, optional),
                  transDocDate (str, optional), transMode (str, optional),
                  consignmentStatus (str, optional), transitType (str, optional)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/extendvalidity",
            headers=headers,
            params=self._email_params(),
            json_body=extend_data,
        )

    # ----------------------------------------------------------------
    # Retrieval — single e-WayBill
    # ----------------------------------------------------------------

    async def get_ewaybill(
        self,
        gstin: str,
        auth_token: str,
        ewb_no: int,
    ) -> Dict[str, Any]:
        """Get full details of a specific e-WayBill by its number."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybill",
            headers=headers,
            params=self._email_params(ewbNo=str(ewb_no)),
        )

    async def get_ewaybill_by_consigner(
        self,
        gstin: str,
        auth_token: str,
        doc_type: str,
        doc_no: str,
    ) -> Dict[str, Any]:
        """Get e-WayBill by document type and number."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillgeneratedbyconsigner",
            headers=headers,
            params=self._email_params(docType=doc_type, docNo=doc_no),
        )

    # ----------------------------------------------------------------
    # Retrieval — lists by date
    # ----------------------------------------------------------------

    async def get_ewaybills_by_date(
        self,
        gstin: str,
        auth_token: str,
        date: str,
    ) -> Dict[str, Any]:
        """
        Get all e-WayBills generated on a date.

        Args:
            date: Date string in dd/MM/YYYY format.
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillsbydate",
            headers=headers,
            params=self._email_params(date=date),
        )

    async def get_ewaybills_for_transporter(
        self,
        gstin: str,
        auth_token: str,
        date: str,
    ) -> Dict[str, Any]:
        """
        Get e-WayBills assigned to you as transporter for a date.

        Args:
            date: Date string in dd/MM/YYYY format.
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillsfortransporter",
            headers=headers,
            params=self._email_params(date=date),
        )

    async def get_ewaybills_for_transporter_by_gstin(
        self,
        gstin: str,
        auth_token: str,
        gen_gstin: str,
        date: str,
    ) -> Dict[str, Any]:
        """Get e-WayBills for a specific generator GSTIN and date."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillsfortransporterbygstin",
            headers=headers,
            params=self._email_params(Gen_gstin=gen_gstin, date=date),
        )

    async def get_ewaybills_for_transporter_by_state(
        self,
        gstin: str,
        auth_token: str,
        state_code: str,
        date: str,
    ) -> Dict[str, Any]:
        """Get e-WayBills for a specific state and date."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillsfortransporterbystate",
            headers=headers,
            params=self._email_params(stateCode=state_code, date=date),
        )

    async def get_ewaybill_report_by_transporter_date(
        self,
        gstin: str,
        auth_token: str,
        date: str,
        state_code: str,
    ) -> Dict[str, Any]:
        """Get e-WayBill report for a state and transporter-assigned date."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillreportbytransporterassigneddate",
            headers=headers,
            params=self._email_params(date=date, stateCode=state_code),
        )

    async def get_ewaybills_of_other_party(
        self,
        gstin: str,
        auth_token: str,
        date: str,
    ) -> Dict[str, Any]:
        """Get e-WayBills generated on you by other parties for a date."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillsofotherparty",
            headers=headers,
            params=self._email_params(date=date),
        )

    async def get_ewaybills_rejected_by_others(
        self,
        gstin: str,
        auth_token: str,
        date: str,
    ) -> Dict[str, Any]:
        """Get e-WayBills rejected by other parties for a date."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getewaybillsrejectedbyothers",
            headers=headers,
            params=self._email_params(date=date),
        )

    # ----------------------------------------------------------------
    # Consolidated e-WayBill
    # ----------------------------------------------------------------

    async def generate_consolidated_ewb(
        self,
        gstin: str,
        auth_token: str,
        consolidated_data: dict,
    ) -> Dict[str, Any]:
        """
        Generate a consolidated e-WayBill for multiple e-WayBills.

        Args:
            consolidated_data: Dict with keys:
                - fromPlace (str), fromState (int)
                - transMode (str): 1=Road, 2=Rail, 3=Air, 4=Ship
                - tripSheetEwbBills (list[dict]): e-WayBill numbers to consolidate
                - vehicleNo (str, optional), transDocNo (str, optional),
                  transDocDate (str, optional)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/gencewb",
            headers=headers,
            params=self._email_params(),
            json_body=consolidated_data,
        )

    async def regenerate_consolidated_ewb(
        self,
        gstin: str,
        auth_token: str,
        regen_data: dict,
    ) -> Dict[str, Any]:
        """
        Regenerate a consolidated e-WayBill (trip sheet).

        Args:
            regen_data: Dict with keys:
                - tripSheetNo (int): Consolidated EWB number
                - fromPlace (str), fromState (int)
                - transMode (str)
                - reasonCode (int), reasonRem (str)
                - vehicleNo (str, optional), transDocNo (str, optional),
                  transDocDate (str, optional)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/regentripsheet",
            headers=headers,
            params=self._email_params(),
            json_body=regen_data,
        )

    async def get_consolidated_ewb(
        self,
        gstin: str,
        auth_token: str,
        trip_sheet_no: int,
    ) -> Dict[str, Any]:
        """Get consolidated e-WayBill (trip sheet) details."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/gettripsheet",
            headers=headers,
            params=self._email_params(tripSheetNo=str(trip_sheet_no)),
        )

    # ----------------------------------------------------------------
    # Multi-vehicle movement
    # ----------------------------------------------------------------

    async def initiate_multi_vehicle(
        self,
        gstin: str,
        auth_token: str,
        init_data: dict,
    ) -> Dict[str, Any]:
        """
        Initiate multi-vehicle movement for an e-WayBill.

        Args:
            init_data: Dict with keys:
                - ewbNo (int)
                - fromPlace (str), fromState (int)
                - toPlace (str), toState (int)
                - totalQuantity (number), unitCode (str)
                - reasonCode (int), reasonRem (str)
                - transMode (str)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/initmulti",
            headers=headers,
            params=self._email_params(),
            json_body=init_data,
        )

    async def add_multi_vehicle(
        self,
        gstin: str,
        auth_token: str,
        add_data: dict,
    ) -> Dict[str, Any]:
        """
        Add a vehicle to multi-vehicle movement.

        Args:
            add_data: Dict with keys:
                - ewbNo (int)
                - vehicleNo (str)
                - groupNo (int)
                - transDocNo (str), transDocDate (str)
                - quantity (int)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/addmulti",
            headers=headers,
            params=self._email_params(),
            json_body=add_data,
        )

    async def change_multi_vehicle(
        self,
        gstin: str,
        auth_token: str,
        change_data: dict,
    ) -> Dict[str, Any]:
        """
        Change/update a vehicle in multi-vehicle movement.

        Args:
            change_data: Dict with keys:
                - ewbNo (int)
                - groupNo (int)
                - oldvehicleNo (str), newVehicleNo (str)
                - oldTranNo (str), newTranNo (str)
                - fromPlace (str), fromState (int)
                - reasonCode (int), reasonRem (str)
        """
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "POST",
            f"{_API_PREFIX}/ewayapi/updtmulti",
            headers=headers,
            params=self._email_params(),
            json_body=change_data,
        )

    # ----------------------------------------------------------------
    # Master data lookups
    # ----------------------------------------------------------------

    async def get_transporter_details(
        self,
        gstin: str,
        auth_token: str,
        transporter_id: str,
    ) -> Dict[str, Any]:
        """Get transporter details by GSTIN or TRANSIN."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/gettransporterdetails",
            headers=headers,
            params=self._email_params(trn_no=transporter_id),
        )

    async def get_gstin_details(
        self,
        gstin: str,
        auth_token: str,
        target_gstin: str,
    ) -> Dict[str, Any]:
        """Get GSTIN details and business information."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/getgstindetails",
            headers=headers,
            params=self._email_params(GSTIN=target_gstin),
        )

    async def get_hsn_details(
        self,
        gstin: str,
        auth_token: str,
        hsn_code: str,
    ) -> Dict[str, Any]:
        """Get HSN/SAC details by code."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/gethsndetailsbyhsncode",
            headers=headers,
            params=self._email_params(hsncode=hsn_code),
        )

    async def get_error_list(
        self,
        gstin: str,
        auth_token: str,
    ) -> Dict[str, Any]:
        """Get list of API error codes and descriptions."""
        headers = self._auth_headers(gstin, auth_token)
        return await self._request(
            "GET",
            f"{_API_PREFIX}/ewayapi/geterrorlist",
            headers=headers,
            params=self._email_params(),
        )
