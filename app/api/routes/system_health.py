# app/api/routes/system_health.py
"""
System Health Dashboard — single-page view of all system components.

Provides:
  GET /admin/system-health       → HTML dashboard (auto-refreshes every 30s)
  GET /admin/system-health/json  → JSON API (for programmatic monitoring)
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import require_admin_token
from app.domain.services.health_check import run_health_check

logger = logging.getLogger("system_health")

router = APIRouter(prefix="/admin/system-health", tags=["system-health"])

templates = Jinja2Templates(directory="app/templates")


@router.get("", dependencies=[Depends(require_admin_token)])
async def health_dashboard(request: Request):
    """Render the full HTML health dashboard."""
    report = await run_health_check()
    return templates.TemplateResponse(
        "admin/system_health.html",
        {
            "request": request,
            "title": "System Health",
            "health": report.to_dict(),
        },
    )


@router.get("/json", dependencies=[Depends(require_admin_token)])
async def health_json():
    """Return health status as JSON (for monitoring tools, curl, etc.)."""
    report = await run_health_check()
    data = report.to_dict()

    # Return 200 for healthy/degraded, 503 for fully down
    status_code = 200 if report.status != "down" else 503
    return JSONResponse(content=data, status_code=status_code)
