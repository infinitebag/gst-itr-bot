from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.whatsapp import router as whatsapp_router
from app.api.routes.whatsapp_health import router as whatsapp_health_router

from app.api.routes.admin_dashboard import router as admin_dashboard_router
from app.api.routes.admin_ca_dashboard import router as admin_ca_dashboard_router
from app.api.routes.admin_invoices import router as admin_invoices_router
from app.api.routes.admin_invoice_pdf import router as admin_invoice_pdf_router
from app.api.routes.admin_whatsapp import router as admin_whatsapp_router

from app.api.routes.gst_debug import router as gst_debug_router
from app.api.routes.gst_gstr1_debug import router as gst_gstr1_debug_router
from app.api.routes.gst_mastergst import router as gst_mastergst_router

api_router = APIRouter()

# Public / health
api_router.include_router(health_router, tags=["health"])
api_router.include_router(whatsapp_health_router, tags=["whatsapp"])
api_router.include_router(whatsapp_router, tags=["whatsapp"])

# Admin
api_router.include_router(admin_dashboard_router, prefix="/admin", tags=["admin"])
api_router.include_router(admin_ca_dashboard_router, prefix="/admin", tags=["admin"])
api_router.include_router(admin_invoices_router, prefix="/admin", tags=["admin"])
api_router.include_router(admin_invoice_pdf_router, prefix="/admin", tags=["admin"])
api_router.include_router(admin_whatsapp_router, prefix="/admin", tags=["admin"])

# GST / Debug
api_router.include_router(gst_debug_router, prefix="/debug", tags=["gst"])
api_router.include_router(gst_gstr1_debug_router, prefix="/debug", tags=["gst"])
api_router.include_router(gst_mastergst_router, prefix="/debug", tags=["gst"])