# app/api/deps.py
"""
Shared FastAPI dependencies used across multiple route modules.

Centralises admin auth so every route module uses the same timing-safe
comparison and consistent error behaviour.  Supports both header-based
(``X-Admin-Token``) and cookie-based (``admin_session`` JWT) auth.
"""

import hmac
import logging

from fastapi import Header, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError

from app.core.config import settings
from app.domain.services.admin_auth import decode_admin_token

logger = logging.getLogger("api.deps")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_browser_request(request: Request) -> bool:
    """Return True if the caller looks like a web browser."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _has_valid_admin_cookie(request: Request) -> bool:
    """Return True if the request carries a valid ``admin_session`` JWT cookie."""
    token = request.cookies.get("admin_session")
    if not token:
        return False
    try:
        decode_admin_token(token)
        return True
    except (JWTError, Exception):
        return False


# ---------------------------------------------------------------------------
# Admin token authentication (header-based + cookie-based)
# ---------------------------------------------------------------------------

async def require_admin_token(
    request: Request,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
) -> None:
    """
    Verify the caller is an authenticated admin.

    Accepts (in priority order):
    1. ``X-Admin-Token`` header — for curl / API clients
    2. ``admin_session`` httpOnly cookie — for browser sessions

    Browser requests without valid auth are **redirected** to the admin
    login page.  API requests receive a 401 JSON error.
    """
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_API_KEY is not configured on the server.",
        )

    # 1. Check X-Admin-Token header (existing behaviour)
    if x_admin_token is not None:
        if hmac.compare_digest(x_admin_token, settings.ADMIN_API_KEY):
            return  # ✓ valid header token
        logger.warning("Invalid admin token attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )

    # 2. Check admin_session cookie (new — browser sessions)
    if _has_valid_admin_cookie(request):
        return  # ✓ valid session cookie

    # 3. No valid auth — redirect browsers, 401 for API
    if _is_browser_request(request):
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/admin/auth/login"},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing X-Admin-Token header.",
    )


def verify_admin_form_token(admin_token: str, request: Request | None = None) -> None:
    """
    Verify admin auth for HTML form POST submissions.

    Accepts (in priority order):
    1. Valid ``admin_session`` cookie (if *request* is provided)
    2. Admin token submitted via the form hidden field

    This means Approve/Reject/Transfer buttons work automatically
    once the admin is logged in via cookie, even though the hidden
    ``admin_token`` field is empty.
    """
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_API_KEY is not configured on the server.",
        )

    # Cookie auth takes priority
    if request is not None and _has_valid_admin_cookie(request):
        return  # ✓ valid session cookie

    # Fall back to form token
    if admin_token and hmac.compare_digest(admin_token, settings.ADMIN_API_KEY):
        return  # ✓ valid form token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid admin token in form.",
    )
