from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.infrastructure.db.models import BusinessClient, Invoice

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin/ca", tags=["admin-ca"])


async def require_admin(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not configured")
    if x_admin_token != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.get("/dashboard")
async def ca_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    stmt = select(BusinessClient)
    result = await db.execute(stmt)
    clients: list[BusinessClient] = list(result.scalars().all())

    rows: list[dict[str, Any]] = []
    for c in clients:
        # Simple heuristic: count invoices where receiver_gstin == client.gstin
        inv_stmt = select(
            func.count(Invoice.id),
            func.max(Invoice.invoice_date),
        ).where(Invoice.receiver_gstin == c.gstin)
        inv_count, last_invoice = (await db.execute(inv_stmt)).one()

        rows.append(
            {
                "name": c.name,
                "gstin": c.gstin,
                "whatsapp_number": c.whatsapp_number,
                "invoice_count": int(inv_count or 0),
                "last_invoice": last_invoice.isoformat() if last_invoice else None,
            }
        )

    return templates.TemplateResponse(
        "admin/ca_dashboard.html",
        {
            "request": request,
            "title": "CA Dashboard",
            "clients": rows,
        },
    )
