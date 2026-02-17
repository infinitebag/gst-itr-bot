# app/api/v1/routes/auth.py
"""
User authentication endpoints: register, login, refresh, profile, link WhatsApp.

Uses bcrypt (via ca_auth helpers) for password hashing and jose for JWT.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.domain.services.ca_auth import hash_password, verify_password
from app.infrastructure.db.models import User

from app.api.v1.deps import get_current_user
from app.api.v1.envelope import ok, error
from app.api.v1.schemas.auth import (
    LoginRequest,
    LinkWhatsAppRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserProfile,
)

logger = logging.getLogger("api.v1.auth")

router = APIRouter(prefix="/auth", tags=["Auth"])


# ---------------------------------------------------------------------------
# JWT helpers (user-specific — separate secret from CA dashboard)
# ---------------------------------------------------------------------------

def _create_user_access_token(user_id: str) -> tuple[str, int]:
    """Return (encoded_jwt, expires_in_seconds)."""
    expire_minutes = settings.USER_JWT_ACCESS_EXPIRE_MINUTES
    exp = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": user_id,
        "type": "user_access",
        "exp": exp,
    }
    token = jwt.encode(payload, settings.USER_JWT_SECRET, algorithm=settings.CA_JWT_ALGORITHM)
    return token, expire_minutes * 60


def _create_user_refresh_token(user_id: str) -> str:
    expire_days = settings.USER_JWT_REFRESH_EXPIRE_DAYS
    exp = datetime.now(timezone.utc) + timedelta(days=expire_days)
    payload = {
        "sub": user_id,
        "type": "user_refresh",
        "exp": exp,
    }
    return jwt.encode(payload, settings.USER_JWT_SECRET, algorithm=settings.CA_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a new user account with email + password.

    Optionally accepts a WhatsApp number to link at registration.
    If no WhatsApp number is provided, a placeholder is generated so
    the existing NOT NULL constraint on ``whatsapp_number`` is satisfied.
    """
    # Check if email already taken
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # If whatsapp_number provided, check uniqueness
    wa_number = body.whatsapp_number or f"api_{uuid.uuid4().hex[:12]}"
    if body.whatsapp_number:
        existing_wa = await db.execute(
            select(User).where(User.whatsapp_number == wa_number)
        )
        if existing_wa.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="WhatsApp number already linked to another account",
            )

    user = User(
        whatsapp_number=wa_number,
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token, expires_in = _create_user_access_token(str(user.id))
    refresh_token = _create_user_refresh_token(str(user.id))

    logger.info("New user registered: %s (email=%s)", user.id, body.email)

    return ok(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ).model_dump(),
        message="Registration successful",
    )


@router.post("/login", response_model=dict)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email + password and receive a JWT pair."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token, expires_in = _create_user_access_token(str(user.id))
    refresh_token = _create_user_refresh_token(str(user.id))

    return ok(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ).model_dump(),
    )


@router.post("/refresh", response_model=dict)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh pair."""
    try:
        payload = jwt.decode(
            body.refresh_token,
            settings.USER_JWT_SECRET,
            algorithms=[settings.CA_JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "user_refresh":
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

    # Verify user still exists
    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    access_token, expires_in = _create_user_access_token(user_id)
    new_refresh = _create_user_refresh_token(user_id)

    return ok(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh,
            expires_in=expires_in,
        ).model_dump(),
    )


@router.get("/me", response_model=dict)
async def me(user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    profile = UserProfile(
        id=str(user.id),
        email=user.email,
        name=user.name,
        whatsapp_number=user.whatsapp_number if not user.whatsapp_number.startswith("api_") else None,
        created_at=user.created_at,
    )
    return ok(data=profile.model_dump())


@router.post("/link-whatsapp", response_model=dict)
async def link_whatsapp(
    body: LinkWhatsAppRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Link a WhatsApp number to the authenticated user's account.

    If the user was created via API (placeholder whatsapp_number), this
    replaces the placeholder with a real number so that WhatsApp conversations
    map to the same user.
    """
    # Check uniqueness
    existing = await db.execute(
        select(User).where(
            User.whatsapp_number == body.whatsapp_number,
            User.id != user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WhatsApp number already linked to another account",
        )

    user.whatsapp_number = body.whatsapp_number
    await db.commit()
    await db.refresh(user)

    logger.info("User %s linked WhatsApp number %s", user.id, body.whatsapp_number)

    return ok(message="WhatsApp number linked successfully")
