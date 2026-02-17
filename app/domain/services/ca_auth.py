# app/domain/services/ca_auth.py
"""
JWT authentication & password hashing for the CA Dashboard.

Usage in routes:
    from app.domain.services.ca_auth import get_current_ca

    @router.get("/ca/dashboard")
    async def dashboard(ca: CAUser = Depends(get_current_ca)):
        ...
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import NoReturn

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.infrastructure.db.models import CAUser
from app.infrastructure.db.repositories.ca_repository import CAUserRepository

# ---------------------------------------------------------------------------
# Password hashing (bcrypt — direct, avoids passlib compat issues)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(ca_id: int, email: str) -> str:
    """Create a short-lived access token (default 30 min)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.CA_JWT_ACCESS_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(ca_id),
        "email": email,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.CA_JWT_SECRET,
        algorithm=settings.CA_JWT_ALGORITHM,
    )


def create_refresh_token(ca_id: int) -> str:
    """Create a long-lived refresh token (default 7 days)."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.CA_JWT_REFRESH_EXPIRE_DAYS
    )
    payload = {
        "sub": str(ca_id),
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.CA_JWT_SECRET,
        algorithm=settings.CA_JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """
    Decode & validate a JWT. Returns the payload dict.
    Raises JWTError on any failure (expired, tampered, etc.).
    """
    return jwt.decode(
        token,
        settings.CA_JWT_SECRET,
        algorithms=[settings.CA_JWT_ALGORITHM],
    )


# ---------------------------------------------------------------------------
# FastAPI dependency – extracts the current CA from the JWT cookie
# ---------------------------------------------------------------------------

async def get_current_ca(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CAUser:
    """
    FastAPI dependency that reads the ``ca_token`` httpOnly cookie,
    validates the JWT, and returns the authenticated :class:`CAUser`.

    On failure it redirects to the login page (for browser requests)
    or raises HTTP 401 (for API requests).
    """
    token: str | None = request.cookies.get("ca_token")

    if not token:
        # Check Authorization header as fallback (for API clients)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        _raise_or_redirect(request)

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            _raise_or_redirect(request)
        ca_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        _raise_or_redirect(request)

    repo = CAUserRepository(db)
    ca = await repo.get_by_id(ca_id)

    if ca is None or not ca.active or not ca.approved:
        _raise_or_redirect(request)

    return ca  # type: ignore[return-value]


def _raise_or_redirect(request: Request) -> NoReturn:
    """Redirect browsers to login; raise 401 for API clients."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        raise HTTPException(
            status_code=303,
            detail="Not authenticated",
            headers={"Location": "/ca/auth/login"},
        )
    raise HTTPException(status_code=401, detail="Not authenticated")
