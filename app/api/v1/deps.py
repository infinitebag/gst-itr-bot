# app/api/v1/deps.py
"""
FastAPI dependencies for the v1 API layer.

Primary dependency: ``get_current_user`` — extracts and validates a Bearer JWT
from the Authorization header and returns the authenticated User ORM object.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Header, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.infrastructure.db.models import User

logger = logging.getLogger("api.v1.deps")


async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency — validates the ``Authorization: Bearer <jwt>`` header
    and returns the authenticated :class:`User`.

    Raises HTTP 401 if the token is missing, invalid, expired, or the user
    does not exist.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]  # strip "Bearer "

    try:
        payload = jwt.decode(
            token,
            settings.USER_JWT_SECRET,
            algorithms=[settings.CA_JWT_ALGORITHM],
        )
    except JWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify token type
    if payload.get("type") != "user_access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
