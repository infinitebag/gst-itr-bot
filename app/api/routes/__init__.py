from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.whatsapp import router as whatsapp_router
from app.api.routes.whatsapp_health import router as whatsapp_health_router

from app.api.routes.admin_dashboard import router as admin_dashboard_router
from app.api.routes.admin_ca_dashboard import router as admin_ca_dashboard_router
from app.api.routes.admin_invoices import router as admin_invoices_router
from app.api.routes.admin_invoice_pdf import router as admin_invoice_pdf_router
from app.api.routes.admin_whatsapp import router as admin_whatsapp_router

from app.api.routes.admin_analytics import router as admin_analytics_router
from app.api.routes.admin_ml_risk import router as admin_ml_risk_router
from app.api.routes.admin_segments import router as admin_segments_router
from app.api.routes.system_health import router as system_health_router

from app.api.routes.admin_ca_management import router as admin_ca_management_router
from app.api.routes.admin_auth import router as admin_auth_router

from app.api.routes.ca_auth import router as ca_auth_router
from app.api.routes.ca_dashboard import router as ca_dashboard_router
from app.api.routes.ca_itr_review import router as ca_itr_review_router
from app.api.routes.ca_gst_review import router as ca_gst_review_router

from app.api.routes.gst_debug import router as gst_debug_router
from app.api.routes.gst_gstr1_debug import router as gst_gstr1_debug_router
from app.api.routes.gst_mastergst import router as gst_mastergst_router
from app.api.routes.gst_periods import router as gst_periods_router
from app.api.routes.gst_annual import router as gst_annual_router
from app.api.routes.itr_api import router as itr_api_router

api_router = APIRouter()

# Public / health
api_router.include_router(health_router, tags=["health"])
api_router.include_router(whatsapp_health_router, tags=["whatsapp"])
api_router.include_router(whatsapp_router, tags=["whatsapp"])

# Admin (routers already have /admin prefix, no extra prefix needed)
api_router.include_router(admin_ca_dashboard_router, tags=["admin"])
api_router.include_router(admin_dashboard_router, tags=["admin"])
api_router.include_router(admin_invoices_router, tags=["admin"])
api_router.include_router(admin_invoice_pdf_router, tags=["admin"])
api_router.include_router(admin_whatsapp_router, tags=["admin"])
api_router.include_router(admin_ca_management_router, tags=["admin-ca-management"])
api_router.include_router(admin_auth_router, tags=["admin-auth"])
api_router.include_router(admin_analytics_router, tags=["admin-analytics"])
api_router.include_router(admin_ml_risk_router, tags=["admin-ml-risk"])
api_router.include_router(admin_segments_router, tags=["admin-segments"])
api_router.include_router(system_health_router, tags=["system-health"])

# CA Dashboard (JWT auth)
api_router.include_router(ca_auth_router, tags=["ca-auth"])
api_router.include_router(ca_dashboard_router, tags=["ca-dashboard"])
api_router.include_router(ca_itr_review_router, tags=["ca-itr-review"])
api_router.include_router(ca_gst_review_router, tags=["ca-gst-review"])

# GST / Debug — only include debug routes in dev/test environments
from app.core.config import settings as _settings

if _settings.ENV in ("dev", "development", "test"):
    api_router.include_router(gst_debug_router, prefix="/debug", tags=["gst-debug"])
    api_router.include_router(gst_gstr1_debug_router, prefix="/debug", tags=["gst-debug"])

# MasterGST integration (always available — protected by its own auth)
api_router.include_router(gst_mastergst_router, prefix="/gst", tags=["gst"])

# GST Period management (monthly compliance)
api_router.include_router(gst_periods_router, prefix="/gst", tags=["gst-periods"])

# GST Annual return (GSTR-9)
api_router.include_router(gst_annual_router, prefix="/gst", tags=["gst-annual"])

# ITR API — compute, PDF download, JSON export (always available)
api_router.include_router(itr_api_router, prefix="/itr", tags=["itr"])