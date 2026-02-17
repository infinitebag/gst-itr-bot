# app/api/v1/routes/ca_auth.py
"""CA authentication endpoints: login, register, refresh, profile."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.domain.services.ca_auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_ca,
    hash_password,
    verify_password,
)
from app.infrastructure.db.models import CAUser
from app.infrastructure.db.repositories.ca_repository import CAUserRepository

from app.api.v1.envelope import ok, error
from app.api.v1.schemas.ca import (
    CALoginRequest,
    CAProfile,
    CARefreshRequest,
    CARegisterRequest,
    CATokenResponse,
)

logger = logging.getLogger("api.v1.ca_auth")

router = APIRouter(prefix="/ca/auth", tags=["CA Auth"])


@router.post("/login", response_model=dict)
async def ca_login(body: CALoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a CA with email + password and receive a JWT pair."""
    repo = CAUserRepository(db)
    ca = await repo.get_by_email(body.email)

    if not ca or not verify_password(body.password, ca.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not ca.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )

    if not ca.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending admin approval.",
        )

    await repo.update_last_login(ca.id)

    access_token = create_access_token(ca.id, ca.email)
    refresh_token = create_refresh_token(ca.id)
    expires_in = settings.CA_JWT_ACCESS_EXPIRE_MINUTES * 60

    logger.info("CA login: id=%s email=%s", ca.id, ca.email)

    return ok(
        data=CATokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ).model_dump(),
    )


@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def ca_register(body: CARegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new CA account (requires admin approval before login)."""
    repo = CAUserRepository(db)

    existing = await repo.get_by_email(body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    ca = await repo.create(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        phone=body.phone,
        membership_number=body.membership_number,
    )

    logger.info("New CA registered: id=%s email=%s", ca.id, ca.email)

    return ok(
        data=CAProfile(
            id=ca.id,
            email=ca.email,
            name=ca.name,
            phone=ca.phone,
            membership_number=ca.membership_number,
            active=ca.active,
            approved=ca.approved,
            created_at=ca.created_at,
        ).model_dump(),
        message="Registration successful. Awaiting admin approval.",
    )


@router.post("/refresh", response_model=dict)
async def ca_refresh(body: CARefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh pair."""
    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    ca_id = int(payload["sub"])
    repo = CAUserRepository(db)
    ca = await repo.get_by_id(ca_id)

    if ca is None or not ca.active or not ca.approved:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CA account not found or inactive",
        )

    access_token = create_access_token(ca.id, ca.email)
    new_refresh = create_refresh_token(ca.id)
    expires_in = settings.CA_JWT_ACCESS_EXPIRE_MINUTES * 60

    return ok(
        data=CATokenResponse(
            access_token=access_token,
            refresh_token=new_refresh,
            expires_in=expires_in,
        ).model_dump(),
    )


@router.get("/me", response_model=dict)
async def ca_me(ca: CAUser = Depends(get_current_ca)):
    """Return the authenticated CA's profile."""
    return ok(
        data=CAProfile(
            id=ca.id,
            email=ca.email,
            name=ca.name,
            phone=ca.phone,
            membership_number=ca.membership_number,
            active=ca.active,
            approved=ca.approved,
            created_at=ca.created_at,
        ).model_dump(),
    )
