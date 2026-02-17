# app/api/v1/__init__.py
"""
Versioned API v1 — aggregates all sub-routers under ``/api/v1``.

Usage in ``main.py``::

    from app.api.v1 import v1_router
    app.include_router(v1_router)
"""

from fastapi import APIRouter

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.invoices import router as invoices_router
from app.api.v1.routes.gst import router as gst_router
from app.api.v1.routes.gst_periods import router as gst_periods_router
from app.api.v1.routes.gst_annual import router as gst_annual_router
from app.api.v1.routes.itr import router as itr_router
from app.api.v1.routes.analytics import router as analytics_router
from app.api.v1.routes.tax_qa import router as tax_qa_router

# CA REST API (for mobile / web apps)
from app.api.v1.routes.ca_auth import router as ca_auth_router
from app.api.v1.routes.ca_clients import router as ca_clients_router
from app.api.v1.routes.ca_reviews import router as ca_reviews_router
from app.api.v1.routes.ca_deadlines import router as ca_deadlines_router
from app.api.v1.routes.admin_ca import router as admin_ca_router
from app.api.v1.routes.admin_tax_rates import router as admin_tax_rates_router
from app.api.v1.routes.knowledge import router as knowledge_router
from app.api.v1.routes.audit import router as audit_router

# Phase 6–10 APIs
from app.api.v1.routes.user_gstins import router as user_gstins_router
from app.api.v1.routes.refunds import router as refunds_router
from app.api.v1.routes.notices import router as notices_router
from app.api.v1.routes.notifications import router as notifications_router

v1_router = APIRouter(prefix="/api/v1")

# End-user APIs
v1_router.include_router(auth_router)
v1_router.include_router(invoices_router)
v1_router.include_router(gst_router)
v1_router.include_router(gst_periods_router)
v1_router.include_router(gst_annual_router)
v1_router.include_router(itr_router)
v1_router.include_router(analytics_router)
v1_router.include_router(tax_qa_router)

# Phase 6–10: Multi-GSTIN, Refunds, Notices, Notifications
v1_router.include_router(user_gstins_router)
v1_router.include_router(refunds_router)
v1_router.include_router(notices_router)
v1_router.include_router(notifications_router)

# CA APIs (JWT Bearer auth)
v1_router.include_router(ca_auth_router)
v1_router.include_router(ca_clients_router)
v1_router.include_router(ca_reviews_router)
v1_router.include_router(ca_deadlines_router)

# Admin APIs (X-Admin-Token / admin_session cookie)
v1_router.include_router(admin_ca_router)
v1_router.include_router(admin_tax_rates_router)
v1_router.include_router(knowledge_router)
v1_router.include_router(audit_router)

__all__ = ["v1_router"]
