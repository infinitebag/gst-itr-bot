# app/api/routes/ca_auth.py
"""
Authentication routes for the CA Dashboard.
Handles registration, login, logout, and token refresh.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.domain.services.ca_auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.infrastructure.db.repositories.ca_repository import CAUserRepository

import time
from collections import defaultdict

# Simple in-memory login rate limiter
_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _check_login_rate_limit(email: str) -> bool:
    """Return True if login is allowed, False if rate-limited."""
    now = time.time()
    attempts = _login_attempts[email]
    # Prune old attempts outside the window
    _login_attempts[email] = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    return len(_login_attempts[email]) < _MAX_LOGIN_ATTEMPTS


def _record_login_attempt(email: str) -> None:
    """Record a failed login attempt."""
    _login_attempts[email].append(time.time())

router = APIRouter(prefix="/ca/auth", tags=["ca-auth"])
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the CA login form."""
    # Show flash message after successful registration
    registered = request.query_params.get("registered")
    info = None
    if registered:
        info = "Account created successfully! Awaiting admin approval before you can log in."
    return templates.TemplateResponse(
        "ca/login.html",
        {"request": request, "title": "CA Login", "error": None, "info": info},
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate CA, set JWT cookie, redirect to dashboard."""
    email = email.strip().lower()

    # Rate limit check
    if not _check_login_rate_limit(email):
        return templates.TemplateResponse(
            "ca/login.html",
            {
                "request": request,
                "title": "CA Login",
                "error": "Too many login attempts. Please try again in 5 minutes.",
            },
            status_code=429,
        )

    repo = CAUserRepository(db)
    ca = await repo.get_by_email(email)

    if ca is None or not verify_password(password, ca.password_hash):
        _record_login_attempt(email)
        return templates.TemplateResponse(
            "ca/login.html",
            {
                "request": request,
                "title": "CA Login",
                "error": "Invalid email or password.",
            },
            status_code=401,
        )

    if not ca.active:
        return templates.TemplateResponse(
            "ca/login.html",
            {
                "request": request,
                "title": "CA Login",
                "error": "Account is deactivated. Contact support.",
            },
            status_code=403,
        )

    if not ca.approved:
        return templates.TemplateResponse(
            "ca/login.html",
            {
                "request": request,
                "title": "CA Login",
                "error": "Your account is pending admin approval. Please wait.",
            },
            status_code=403,
        )

    # Update last login timestamp
    await repo.update_last_login(ca.id)

    # Create JWT tokens
    access_token = create_access_token(ca.id, ca.email)
    refresh_token = create_refresh_token(ca.id)

    response = RedirectResponse(url="/ca/dashboard", status_code=303)
    response.set_cookie(
        key="ca_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=30 * 60,  # 30 minutes
    )
    response.set_cookie(
        key="ca_refresh",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,  # 7 days
    )
    return response


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Render the CA registration form."""
    return templates.TemplateResponse(
        "ca/register.html",
        {"request": request, "title": "CA Registration", "error": None},
    )


@router.post("/register")
async def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    membership_number: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Create a new CA account."""
    email = email.strip().lower()

    # Validation
    if password != confirm_password:
        return templates.TemplateResponse(
            "ca/register.html",
            {
                "request": request,
                "title": "CA Registration",
                "error": "Passwords do not match.",
            },
            status_code=400,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            "ca/register.html",
            {
                "request": request,
                "title": "CA Registration",
                "error": "Password must be at least 8 characters.",
            },
            status_code=400,
        )

    repo = CAUserRepository(db)

    # Check if email already registered
    existing = await repo.get_by_email(email)
    if existing:
        return templates.TemplateResponse(
            "ca/register.html",
            {
                "request": request,
                "title": "CA Registration",
                "error": "An account with this email already exists.",
            },
            status_code=409,
        )

    # Create the CA account
    password_hashed = hash_password(password)
    ca = await repo.create(
        email=email,
        password_hash=password_hashed,
        name=name.strip(),
        phone=phone.strip() or None,
        membership_number=membership_number.strip() or None,
    )

    # Redirect to login with success message (admin approval required)
    return RedirectResponse(url="/ca/auth/login?registered=1", status_code=303)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout():
    """Clear JWT cookies and redirect to login."""
    response = RedirectResponse(url="/ca/auth/login", status_code=303)
    response.delete_cookie("ca_token")
    response.delete_cookie("ca_refresh")
    return response


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

@router.post("/refresh")
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Use the refresh token to get a new access token."""
    refresh = request.cookies.get("ca_refresh")
    if not refresh:
        raise HTTPException(status_code=401, detail="No refresh token")

    try:
        payload = decode_token(refresh)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        ca_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    repo = CAUserRepository(db)
    ca = await repo.get_by_id(ca_id)
    if ca is None or not ca.active:
        raise HTTPException(status_code=401, detail="Account not found or inactive")

    new_access = create_access_token(ca.id, ca.email)

    response = RedirectResponse(url="/ca/dashboard", status_code=303)
    response.set_cookie(
        key="ca_token",
        value=new_access,
        httponly=True,
        samesite="lax",
        max_age=30 * 60,
    )
    return response
