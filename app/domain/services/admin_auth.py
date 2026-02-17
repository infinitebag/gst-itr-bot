# app/domain/services/admin_auth.py
"""
Admin authentication service — JWT-based session auth for the admin dashboard.

No database table needed. The admin is a single super-admin identified by
ADMIN_API_KEY. On login, we validate the key and issue a signed JWT stored
in an httpOnly cookie.
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

logger = logging.getLogger("admin_auth")


# ---------------------------------------------------------------------------
# Key verification
# ---------------------------------------------------------------------------

def verify_admin_key(key: str) -> bool:
    """Timing-safe comparison of the provided key against ADMIN_API_KEY."""
    if not settings.ADMIN_API_KEY:
        return False
    return hmac.compare_digest(key, settings.ADMIN_API_KEY)


# ---------------------------------------------------------------------------
# JWT creation / decoding
# ---------------------------------------------------------------------------

def create_admin_token() -> str:
    """Create a signed JWT for an authenticated admin session."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ADMIN_JWT_ACCESS_EXPIRE_MINUTES,
    )
    payload = {
        "sub": "admin",
        "type": "admin_access",
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.ADMIN_JWT_SECRET,
        algorithm="HS256",
    )


def decode_admin_token(token: str) -> dict:
    """
    Decode and validate an admin JWT.

    Returns the payload dict on success.
    Raises ``JWTError`` on invalid / expired tokens.
    """
    payload = jwt.decode(
        token,
        settings.ADMIN_JWT_SECRET,
        algorithms=["HS256"],
    )
    if payload.get("type") != "admin_access":
        raise JWTError("Invalid token type")
    if payload.get("sub") != "admin":
        raise JWTError("Invalid token subject")
    return payload
