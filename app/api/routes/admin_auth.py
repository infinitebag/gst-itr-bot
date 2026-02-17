# app/api/routes/admin_auth.py
"""
Admin login / logout routes — cookie-based session auth.

Allows admins to log in via a web form (entering ADMIN_API_KEY),
receive an httpOnly JWT cookie, and browse all admin pages normally.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.domain.services.admin_auth import create_admin_token, verify_admin_key

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Render the admin login form."""
    # If already authenticated via cookie, redirect to admin
    from app.api.deps import _has_valid_admin_cookie

    if _has_valid_admin_cookie(request):
        return RedirectResponse(url="/admin/ca/list", status_code=303)

    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "title": "Admin Login", "error": None},
    )


@router.post("/login")
async def admin_login(
    request: Request,
    admin_key: str = Form(...),
):
    """Validate admin API key, set session cookie, redirect to dashboard."""
    if not verify_admin_key(admin_key):
        return templates.TemplateResponse(
            "admin/login.html",
            {
                "request": request,
                "title": "Admin Login",
                "error": "Invalid admin key.",
            },
            status_code=403,
        )

    # Create JWT and set httpOnly cookie
    token = create_admin_token()
    response = RedirectResponse(url="/admin/ca/list", status_code=303)
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.ADMIN_JWT_ACCESS_EXPIRE_MINUTES * 60,
    )
    return response


@router.post("/logout")
async def admin_logout():
    """Clear the admin session cookie and redirect to login."""
    response = RedirectResponse(url="/admin/auth/login", status_code=303)
    response.delete_cookie(key="admin_session")
    return response
